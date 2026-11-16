"""Study sessions: start one, get its parts one at a time, send answers, finish.

A session's parts come from one of two places, chosen by SESSION_SOURCE in .env:

  sample  The hand-written sample in assets/fixtures/sessions/, handed out part
          by part. Costs nothing and needs no key. This is the default.
  agent   Built for this student by the session agent (app/agent.py), which
          calls Claude. Each session costs money.

The requests and replies are the same either way, so the browser cannot tell
the difference except by what the session says.

Sessions are held in memory and are lost when the server restarts.
"""

import base64
import binascii
import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Protocol
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from app.agent import Agent, AgentError, Brief, ChatAnswer, PlannedPart, Question, Turn, sources_used
from app.articles import get_articles
from app.config import REPO_ROOT, settings
from app.llm import ClaudeLLM, LLMError, Usage
from app.region import get_region
from app.session_schemas import (
    SESSION_FORMAT,
    AnswerReply,
    ChatReply,
    ChatRequest,
    ClickAnswer,
    ClickCase,
    NextReply,
    Part,
    PlanItem,
    Question as QuestionReply,
    RecordedSession,
    ReplyRequest,
    Scope,
    SessionStart,
    SessionState,
    StartRequest,
    Summary,
    TutorQuestion,
)

SAMPLE_PATH = REPO_ROOT / "assets" / "fixtures" / "sessions" / "coronary_arteries.json"

MAX_NOTES_BYTES = 20 * 1024 * 1024

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

# Shown in the terminal the backend runs in, next to uvicorn's own lines.
log = logging.getLogger("uvicorn.error")

# Parts are built ahead of the student on these threads.
_builders = ThreadPoolExecutor(max_workers=4, thread_name_prefix="lumen-build")


class Tutor(Protocol):
    """Where a session's parts come from."""

    name: str

    def plan(self) -> list[PlanItem]: ...
    def next_part(self, answers: list[ClickAnswer]) -> Part | None: ...
    def summary(self, answers: list[ClickAnswer]) -> Summary: ...


class SampleTutor:
    """Hands out the hand-written sample, whatever was asked."""

    name = "sample"

    def __init__(self, script: RecordedSession):
        self.script = script
        self.sent = 0

    def plan(self) -> list[PlanItem]:
        return self.script.plan

    def next_part(self, answers: list[ClickAnswer]) -> Part | None:
        if self.sent >= len(self.script.parts):
            return None
        self.sent += 1
        return self.script.parts[self.sent - 1]

    def summary(self, answers: list[ClickAnswer]) -> Summary:
        return self.script.summary


class AgentTutor:
    """Parts built by the session agent, each one prepared while the student works on the one before."""

    name = "agent"

    def __init__(self, agent: Agent, brief: Brief):
        self.agent = agent
        self.brief = brief
        self.building: dict[str, Future[Part]] = {}
        self.replanned: set[str] = set()  # cases whose answers have already been looked at
        self.dropped: list[str] = []  # parts given up on, with the reason

    def plan(self) -> list[PlanItem]:
        return [PlanItem(part_id=item.part_id, title=item.title, kind=item.kind) for item in self.brief.plan]

    def prepare(self, index: int) -> None:
        """Start building the part at this place in the plan, unless it is already under way."""
        if index < len(self.brief.plan):
            item = self.brief.plan[index]
            if item.part_id not in self.building:
                self.building[item.part_id] = _builders.submit(self.agent.build, self.brief, item)

    def next_part(self, answers: list[ClickAnswer]) -> Part | None:
        given = len(self.brief.built)
        last = self.brief.built[-1] if self.brief.built else None
        # After a case the student got wrong, the agent may put one extra part before the rest.
        if isinstance(last, ClickCase) and last.id not in self.replanned:
            self.replanned.add(last.id)
            tries = [answer for answer in answers if answer.part_id == last.id]
            if any(not answer.correct for answer in tries):
                extra = self.agent.decide(self.brief, last, tries)
                if extra is not None:
                    self.brief.plan.insert(given, extra)
        while given < len(self.brief.plan):
            item = self.brief.plan[given]
            self.prepare(given)
            try:
                part = self.building.pop(item.part_id).result()
            except AgentError as error:
                # A part that never passed its checks is left out; the session goes on without it.
                self.dropped.append(f"{item.title}: {error.problems[0]}")
                self.brief.plan.pop(given)
                continue
            self.brief.built.append(part)
            self.prepare(given + 1)
            return part
        return None

    def chat(self, text: str, selected: list[str], part_id: str | None) -> tuple[ChatAnswer, bool]:
        """Answer the student, and swap in a new rest of the plan if the agent gave one. Returns the answer and whether the plan changed."""
        on_screen = next((part.title for part in self.brief.built if part.id == part_id), None)
        answer = self.agent.chat(self.brief, text, selected, on_screen)
        said = " ".join(statement.text for statement in answer.statements)
        self.brief.conversation += [Turn("student", text), Turn("tutor", said)]
        if answer.new_plan is None:
            return answer, False
        given = len(self.brief.built)
        for item in self.brief.plan[given:]:
            # Parts being built for the old plan are no longer wanted. One already running finishes and is ignored.
            future = self.building.pop(item.part_id, None)
            if future is not None:
                future.cancel()
        self.brief.plan[given:] = answer.new_plan
        self.prepare(given)
        return answer, True

    def summary(self, answers: list[ClickAnswer]) -> Summary:
        solid, shaky = self.agent.summarise(self.brief, answers)
        return Summary(solid=solid, shaky=shaky, sources=sources_used(self.brief.built))


@dataclass
class Session:
    """Everything the backend remembers about one student's run."""

    request: str
    tutor: Tutor
    usage: Usage
    notes_name: str | None = None
    notes: bytes = b""
    sent: list[Part] = field(default_factory=list)
    finished: bool = False
    # Set while the tutor waits for the student to answer a question; there is no plan until then.
    question: Question | None = None
    answers: list[ClickAnswer] = field(default_factory=list)
    # One request at a time per session: building and replanning change its state.
    lock: threading.Lock = field(default_factory=threading.Lock)


_sessions: dict[str, Session] = {}


@lru_cache
def load_sample() -> RecordedSession:
    """Load and check the sample session, so it can't drift from the models."""
    return RecordedSession.model_validate_json(SAMPLE_PATH.read_text(encoding="utf-8"))


def make_agent(usage: Usage) -> Agent:
    """The agent for a new session. Tests replace this to supply scripted replies."""
    return Agent(ClaudeLLM(), get_region(), get_articles(), usage)


def _find(session_id: str) -> Session:
    try:
        return _sessions[session_id]
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail="No such session. Sessions are kept in memory, so it may have been lost when the server restarted.",
        ) from None


def _read_pdf(data: str) -> bytes:
    """Decode an uploaded PDF, rejecting anything that isn't one."""
    try:
        content = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=422, detail="notes.data is not valid base64") from None
    if len(content) > MAX_NOTES_BYTES:
        raise HTTPException(status_code=413, detail=f"notes are larger than {MAX_NOTES_BYTES // (1024 * 1024)} MB")
    if not content.startswith(b"%PDF"):
        raise HTTPException(status_code=422, detail="notes must be a PDF file")
    return content


def _agent_failed(error: Exception) -> HTTPException:
    """Turn any failure of the agent or of Claude into a reply the browser can show.

    Failures nobody foresaw are caught too. Left alone they become a bare 500,
    which the browser cannot read from another origin, so the student would be
    told the backend can't be reached when it is running fine.
    """
    if isinstance(error, AgentError):
        reason = error.problems[0]
    elif isinstance(error, LLMError):
        reason = str(error)
    else:
        log.exception("The session agent failed in a way that was not foreseen")
        reason = f"an unexpected error ({type(error).__name__}: {error})"
    return HTTPException(status_code=502, detail=f"The tutor could not do that: {reason}")


def _opening(session_id: str, session: Session) -> SessionStart | TutorQuestion:
    """The reply that opens a session: the tutor's question if it has one, otherwise the plan."""
    region = get_region().id
    if session.question is not None:
        question = QuestionReply(text=session.question.text, options=session.question.options)
        return TutorQuestion(format=SESSION_FORMAT, session_id=session_id, region=region, request=session.request, question=question)
    tutor = session.tutor
    if isinstance(tutor, AgentTutor):
        scope = tutor.brief.scope or Scope(can_show=[], words_only=[])
        tutor.prepare(0)  # start on the first part while the browser shows the plan
    else:
        scope = load_sample().scope
    return SessionStart(format=SESSION_FORMAT, session_id=session_id, region=region, request=session.request, scope=scope, plan=tutor.plan())


@router.post("")
def start_session(body: StartRequest) -> SessionStart | TutorQuestion:
    """Start a session from what the student asked for and, optionally, their notes.

    With the agent, the reply may be a question for the student instead of a plan.
    They answer it with POST /api/sessions/{id}/reply.
    """
    notes = _read_pdf(body.notes.data) if body.notes else b""
    notes_name = body.notes.filename if body.notes else None
    session_id = uuid4().hex
    request = body.request.strip()
    usage = Usage()
    question: Question | None = None

    if settings.session_source == "agent":
        try:
            agent = make_agent(usage)
            brief = Brief(request=request)
            if body.notes:
                brief.facts = agent.read_notes(request, body.notes.data, body.notes.filename)
            question = agent.plan(brief)
        except Exception as error:
            raise _agent_failed(error) from None
        tutor: Tutor = AgentTutor(agent, brief)
    else:
        tutor = SampleTutor(load_sample())

    session = Session(request=request, tutor=tutor, usage=usage, notes_name=notes_name, notes=notes, question=question)
    _sessions[session_id] = session
    return _opening(session_id, session)


@router.post("/{session_id}/reply")
def reply_to_tutor(session_id: str, body: ReplyRequest) -> SessionStart | TutorQuestion:
    """The student's answer to the tutor's question. The tutor plans, or asks one more thing."""
    session = _find(session_id)
    with session.lock:
        tutor = session.tutor
        if session.question is None or not isinstance(tutor, AgentTutor):
            raise HTTPException(status_code=409, detail="The tutor isn't waiting for an answer in this session.")
        said = [Turn("tutor", session.question.text), Turn("student", body.text.strip())]
        tutor.brief.conversation += said
        try:
            session.question = tutor.agent.plan(tutor.brief)
        except Exception as error:
            # Forget the answer, so trying again doesn't give it twice.
            del tutor.brief.conversation[-len(said) :]
            raise _agent_failed(error) from None
        return _opening(session_id, session)


@router.post("/{session_id}/chat")
def chat(session_id: str, body: ChatRequest) -> ChatReply:
    """Something the student says mid-session: a question, or a wish to go another way. The tutor answers and may change the plan."""
    session = _find(session_id)
    with session.lock:
        tutor = session.tutor
        if session.question is not None:
            raise HTTPException(status_code=409, detail="The tutor is waiting for an answer to its question; send it with /reply.")
        if not isinstance(tutor, AgentTutor):
            raise HTTPException(status_code=409, detail="The tutor is switched off: this backend hands out the sample session, which can't answer questions.")
        try:
            answer, changed = tutor.chat(body.text.strip(), body.selected, body.part_id)
        except Exception as error:
            raise _agent_failed(error) from None
        return ChatReply(statements=answer.statements, point_to=answer.point_to, plan=tutor.plan(), plan_changed=changed)


@router.post("/{session_id}/next")
def next_part(session_id: str) -> NextReply:
    """The next part of the session, or `done` once there are no more."""
    session = _find(session_id)
    with session.lock:
        if session.question is not None:
            raise HTTPException(status_code=409, detail="The tutor is waiting for an answer to its question before it plans.")
        try:
            part = session.tutor.next_part(session.answers)
        except Exception as error:
            raise _agent_failed(error) from None
        if part is not None:
            session.sent.append(part)
        return NextReply(part=part, plan=session.tutor.plan(), done=part is None)


@router.post("/{session_id}/answers")
def record_answer(session_id: str, answer: ClickAnswer) -> AnswerReply:
    """Record one click on a case. The agent reads these to decide what comes next."""
    session = _find(session_id)
    with session.lock:
        sent = {part.id: part.kind for part in session.sent}
        if sent.get(answer.part_id) != "click_case":
            raise HTTPException(status_code=422, detail=f"{answer.part_id!r} is not a case this session has been sent")
        session.answers.append(answer)
        return AnswerReply(plan=session.tutor.plan())


@router.post("/{session_id}/finish")
def finish_session(session_id: str) -> Summary:
    """End the session and get its summary."""
    session = _find(session_id)
    with session.lock:
        try:
            summary = session.tutor.summary(session.answers)
        except Exception as error:
            raise _agent_failed(error) from None
        session.finished = True
        return summary


@router.get("/{session_id}")
def session_state(session_id: str) -> SessionState:
    """What the backend holds for a session: for checking that answers arrived, and what a session cost."""
    session = _find(session_id)
    tutor = session.tutor
    return SessionState(
        session_id=session_id,
        request=session.request,
        conversation=[f"{turn.who}: {turn.text}" for turn in tutor.brief.conversation] if isinstance(tutor, AgentTutor) else [],
        source=tutor.name,
        notes=session.notes_name,
        notes_bytes=len(session.notes),
        parts_sent=len(session.sent),
        finished=session.finished,
        answers=session.answers,
        dropped=tutor.dropped if isinstance(tutor, AgentTutor) else [],
        claude_calls=session.usage.calls,
        input_tokens=session.usage.input_tokens + session.usage.cache_read_tokens + session.usage.cache_write_tokens,
        output_tokens=session.usage.output_tokens,
    )
