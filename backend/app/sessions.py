"""Study sessions: start one, get its parts one at a time, send answers, finish.

A session's parts come from one of two places, chosen by SESSION_SOURCE in .env:

  sample  The hand-written sample in assets/fixtures/sessions/, handed out part
          by part. Costs nothing and needs no key. This is the default.
  agent   Built for this student by the session agent (app/agent.py), which
          calls Claude. Each session costs money.

The requests and replies are the same either way, so the browser cannot tell
the difference except by what the session says.

Every session is saved to the store (app/store.py) after each request that
changes it, and loaded from there when it isn't in memory, so a session survives
a restart and can be picked up the next day. Parts that were being built ahead
of the student are not saved; they are built again when needed.
"""

import base64
import binascii
import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from typing import Any, Protocol
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from app.agent import PART_ADAPTER, Agent, AgentError, Brief, ChatAnswer, NoteFact, PlannedPart, Question, Turn, sources_used
from app.articles import get_articles
from app.config import REPO_ROOT, settings
from app.llm import ClaudeLLM, LLMError, Usage
from app.region import get_region
from app.store import get_store
from app.session_schemas import (
    SESSION_FORMAT,
    AnswerReply,
    ChatReply,
    ChatRequest,
    ClickAnswer,
    ClickCase,
    NextReply,
    OpeningAnswer,
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


class ExploreOnlyTutor:
    """A session for clicking around the model with the tutor switched off: no parts, and no answers."""

    name = "sample"

    def plan(self) -> list[PlanItem]:
        return []

    def next_part(self, answers: list[ClickAnswer]) -> Part | None:
        return None

    def summary(self, answers: list[ClickAnswer]) -> Summary:
        return Summary(solid=[], shaky=[], sources=[])


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
    notes_bytes: int = 0  # the PDF itself is not kept: the facts read from it are in the brief
    sent: list[Part] = field(default_factory=list)
    finished: bool = False
    # Set while the tutor waits for the student to answer a question; there is no plan until then.
    question: Question | None = None
    answers: list[ClickAnswer] = field(default_factory=list)
    summary: Summary | None = None
    # One request at a time per session: building and replanning change its state.
    lock: threading.Lock = field(default_factory=threading.Lock)


# Sessions in use, so each request needn't read the store. Every one is also saved there.
_sessions: dict[str, Session] = {}
_loading = threading.Lock()  # so two requests can't load the same session twice


@lru_cache
def load_sample() -> RecordedSession:
    """Load and check the sample session, so it can't drift from the models."""
    return RecordedSession.model_validate_json(SAMPLE_PATH.read_text(encoding="utf-8"))


def make_agent(usage: Usage) -> Agent:
    """The agent for a new session. Tests replace this to supply scripted replies."""
    return Agent(ClaudeLLM(), get_region(), get_articles(), usage)


def _find(session_id: str) -> Session:
    """The session with this id: from memory, or else from the store."""
    with _loading:
        if session_id in _sessions:
            return _sessions[session_id]
        data = get_store().load(session_id)
        if data is not None:
            try:
                _sessions[session_id] = _restore(data)
                return _sessions[session_id]
            except Exception:
                log.exception("Session %s was saved but could not be loaded", session_id)
                raise HTTPException(status_code=410, detail="This session was saved by an older version of Lumen and can't be reopened. Start a new one.") from None
    raise HTTPException(
        status_code=404, detail=f"No such session. Sessions are kept for {settings.session_days:g} days after they were last used."
    )


# Saving and loading. The format is plain JSON; bump SAVE_VERSION when it changes in a way old rows can't be read.

SAVE_VERSION = 1


def _dump_brief(brief: Brief) -> dict[str, Any]:
    return {
        "request": brief.request,
        "facts": [asdict(fact) for fact in brief.facts],
        "conversation": [asdict(turn) for turn in brief.conversation],
        "scope": brief.scope.model_dump() if brief.scope else None,
        "plan": [asdict(item) for item in brief.plan],
        "built": [part.model_dump(mode="json", by_alias=True) for part in brief.built],
    }


def _restore_brief(data: dict[str, Any]) -> Brief:
    return Brief(
        request=data["request"],
        facts=[NoteFact(**fact) for fact in data["facts"]],
        conversation=[Turn(**turn) for turn in data["conversation"]],
        scope=Scope.model_validate(data["scope"]) if data["scope"] else None,
        plan=[PlannedPart(**item) for item in data["plan"]],
        built=[PART_ADAPTER.validate_python(part) for part in data["built"]],
    )


def _dump(session: Session) -> dict[str, Any]:
    """Everything needed to carry on with a session later, as plain JSON."""
    tutor = session.tutor
    data: dict[str, Any] = {
        "version": SAVE_VERSION,
        "request": session.request,
        "notes_name": session.notes_name,
        "notes_bytes": session.notes_bytes,
        "sent": [part.model_dump(mode="json", by_alias=True) for part in session.sent],
        "finished": session.finished,
        "question": asdict(session.question) if session.question else None,
        "answers": [answer.model_dump(mode="json") for answer in session.answers],
        "usage": asdict(session.usage),
        "summary": session.summary.model_dump(mode="json") if session.summary else None,
    }
    if isinstance(tutor, AgentTutor):
        data["tutor"] = {"kind": "agent", "brief": _dump_brief(tutor.brief), "replanned": sorted(tutor.replanned), "dropped": tutor.dropped}
    elif isinstance(tutor, SampleTutor):
        data["tutor"] = {"kind": "sample", "sent": tutor.sent}
    else:
        data["tutor"] = {"kind": "explore"}
    return data


def _restore(data: dict[str, Any]) -> Session:
    """A session saved with _dump, ready to carry on."""
    if data.get("version") != SAVE_VERSION:
        raise ValueError(f"saved with format version {data.get('version')}, this backend reads {SAVE_VERSION}")
    usage = Usage(**data["usage"])
    saved = data["tutor"]
    tutor: Tutor
    if saved["kind"] == "agent":
        agent_tutor = AgentTutor(make_agent(usage), _restore_brief(saved["brief"]))
        agent_tutor.replanned = set(saved["replanned"])
        agent_tutor.dropped = list(saved["dropped"])
        tutor = agent_tutor
    elif saved["kind"] == "sample":
        sample_tutor = SampleTutor(load_sample())
        sample_tutor.sent = saved["sent"]
        tutor = sample_tutor
    else:
        tutor = ExploreOnlyTutor()
    return Session(
        request=data["request"],
        tutor=tutor,
        usage=usage,
        notes_name=data["notes_name"],
        notes_bytes=data["notes_bytes"],
        sent=[PART_ADAPTER.validate_python(part) for part in data["sent"]],
        finished=data["finished"],
        question=Question(**data["question"]) if data["question"] else None,
        answers=[ClickAnswer.model_validate(answer) for answer in data["answers"]],
        summary=Summary.model_validate(data["summary"]) if data["summary"] else None,
    )


def _save(session_id: str, session: Session) -> None:
    get_store().save(session_id, _dump(session))


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


def _opening(session_id: str, session: Session, answer: ChatAnswer | None = None) -> SessionStart | TutorQuestion:
    """The reply that opens a session: the tutor's question if it has one, otherwise the plan (empty when exploring) and any answer."""
    region = get_region().id
    if session.question is not None:
        question = QuestionReply(text=session.question.text, options=session.question.options)
        return TutorQuestion(format=SESSION_FORMAT, session_id=session_id, region=region, request=session.request, question=question)
    tutor = session.tutor
    if isinstance(tutor, AgentTutor):
        scope = tutor.brief.scope or Scope(can_show=[], words_only=[])
        tutor.prepare(0)  # start on the first part while the browser shows the plan
    elif isinstance(tutor, SampleTutor):
        scope = load_sample().scope
    else:
        scope = Scope(can_show=[], words_only=[])
    opening = OpeningAnswer(statements=answer.statements, point_to=answer.point_to) if answer else None
    return SessionStart(
        format=SESSION_FORMAT, session_id=session_id, region=region, request=session.request, scope=scope, plan=tutor.plan(), answer=opening
    )


def _answered(brief: Brief, said: str, answer: ChatAnswer) -> None:
    """Record what the student said and the tutor's answer, so later work knows about them."""
    brief.conversation += [Turn("student", said), Turn("tutor", " ".join(statement.text for statement in answer.statements))]


@router.post("", response_model_exclude_none=True)
def start_session(body: StartRequest) -> SessionStart | TutorQuestion:
    """Start a session from what the student asked for and, optionally, their notes.

    With the agent, the reply may be a question for the student instead of a plan
    (they answer it with POST /api/sessions/{id}/reply), or an answer and no plan
    when they asked a question. An empty request opens the model to explore,
    with no call to Claude until they ask something.
    """
    notes = _read_pdf(body.notes.data) if body.notes else b""  # checked here, then only its size is kept
    notes_name = body.notes.filename if body.notes else None
    session_id = uuid4().hex
    request = body.request.strip()
    usage = Usage()
    question: Question | None = None
    answer: ChatAnswer | None = None

    if settings.session_source == "agent":
        try:
            agent = make_agent(usage)
            brief = Brief(request=request)
            if body.notes:
                brief.facts = agent.read_notes(request or "Anything in these notes", body.notes.data, body.notes.filename)
            if request:
                opened = agent.plan(brief)
                question = opened if isinstance(opened, Question) else None
                answer = opened if isinstance(opened, ChatAnswer) else None
                if answer:
                    _answered(brief, request, answer)
        except Exception as error:
            raise _agent_failed(error) from None
        tutor: Tutor = AgentTutor(agent, brief)
    else:
        tutor = SampleTutor(load_sample()) if request else ExploreOnlyTutor()

    shown = request or f"Explore the {get_region().name.lower()}"
    session = Session(request=shown, tutor=tutor, usage=usage, notes_name=notes_name, notes_bytes=len(notes), question=question)
    _sessions[session_id] = session
    reply = _opening(session_id, session, answer)
    _save(session_id, session)
    return reply


@router.post("/{session_id}/reply", response_model_exclude_none=True)
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
            opened = tutor.agent.plan(tutor.brief)
        except Exception as error:
            # Forget the answer, so trying again doesn't give it twice.
            del tutor.brief.conversation[-len(said) :]
            raise _agent_failed(error) from None
        session.question = opened if isinstance(opened, Question) else None
        answer = opened if isinstance(opened, ChatAnswer) else None
        if answer:
            tutor.brief.conversation.append(Turn("tutor", " ".join(statement.text for statement in answer.statements)))
        reply = _opening(session_id, session, answer)
        _save(session_id, session)
        return reply


@router.post("/{session_id}/chat")
def chat(session_id: str, body: ChatRequest) -> ChatReply:
    """Something the student says mid-session: a question, or a wish to go another way. The tutor answers and may change the plan."""
    session = _find(session_id)
    with session.lock:
        tutor = session.tutor
        if session.question is not None:
            raise HTTPException(status_code=409, detail="The tutor is waiting for an answer to its question; send it with /reply.")
        if not isinstance(tutor, AgentTutor):
            raise HTTPException(status_code=409, detail="The tutor is switched off (SESSION_SOURCE is sample), so it can't answer questions.")
        try:
            answer, changed = tutor.chat(body.text.strip(), body.selected, body.part_id)
        except Exception as error:
            raise _agent_failed(error) from None
        finally:
            _save(session_id, session)  # what it cost, even when it failed
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
            if part is not None:
                session.sent.append(part)
        except Exception as error:
            raise _agent_failed(error) from None
        finally:
            _save(session_id, session)  # parts given up on and replanning count even when this request failed
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
        _save(session_id, session)
        return AnswerReply(plan=session.tutor.plan())


@router.post("/{session_id}/finish")
def finish_session(session_id: str) -> Summary:
    """End the session and get its summary."""
    session = _find(session_id)
    with session.lock:
        if session.summary is not None:
            return session.summary  # already written; asking again costs nothing
        try:
            session.summary = session.tutor.summary(session.answers)
        except Exception as error:
            raise _agent_failed(error) from None
        finally:
            _save(session_id, session)
        session.finished = True
        _save(session_id, session)
        return session.summary


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
        notes_bytes=session.notes_bytes,
        parts_sent=len(session.sent),
        finished=session.finished,
        answers=session.answers,
        dropped=tutor.dropped if isinstance(tutor, AgentTutor) else [],
        claude_calls=session.usage.calls,
        input_tokens=session.usage.input_tokens + session.usage.cache_read_tokens + session.usage.cache_write_tokens,
        output_tokens=session.usage.output_tokens,
    )
