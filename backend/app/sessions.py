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
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Protocol
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from app.agent import Agent, AgentError, Brief, PlannedPart, sources_used
from app.articles import get_articles
from app.config import REPO_ROOT, settings
from app.llm import ClaudeLLM, LLMError, Usage
from app.region import get_region
from app.session_schemas import (
    SESSION_FORMAT,
    AnswerReply,
    ClickAnswer,
    ClickCase,
    NextReply,
    Part,
    PlanItem,
    RecordedSession,
    Scope,
    SessionStart,
    SessionState,
    StartRequest,
    Summary,
)

SAMPLE_PATH = REPO_ROOT / "assets" / "fixtures" / "sessions" / "coronary_arteries.json"

MAX_NOTES_BYTES = 20 * 1024 * 1024

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

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

    def summary(self, answers: list[ClickAnswer]) -> Summary:
        solid, shaky = self.agent.summarise(self.brief, answers)
        return Summary(solid=solid, shaky=shaky, sources=sources_used(self.brief.built))


@dataclass
class Session:
    """Everything the backend remembers about one student's run."""

    start: SessionStart
    tutor: Tutor
    usage: Usage
    notes_name: str | None = None
    notes: bytes = b""
    sent: list[Part] = field(default_factory=list)
    finished: bool = False
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
    """Turn a failure of the agent or of Claude into a reply the browser can show."""
    reason = error.problems[0] if isinstance(error, AgentError) else str(error)
    return HTTPException(status_code=502, detail=f"The tutor could not do that: {reason}")


@router.post("")
def start_session(body: StartRequest) -> SessionStart:
    """Start a session from what the student asked for and, optionally, their notes."""
    notes = _read_pdf(body.notes.data) if body.notes else b""
    notes_name = body.notes.filename if body.notes else None
    session_id = uuid4().hex
    request = body.request.strip()
    usage = Usage()

    if settings.session_source == "agent":
        agent = make_agent(usage)
        brief = Brief(request=request)
        try:
            if body.notes:
                brief.facts = agent.read_notes(request, body.notes.data, body.notes.filename)
            agent.plan(brief)
        except (LLMError, AgentError) as error:
            raise _agent_failed(error) from None
        tutor: Tutor = AgentTutor(agent, brief)
        scope = brief.scope or Scope(can_show=[], words_only=[])
        tutor.prepare(0)  # start on the first part while the browser shows the plan
    else:
        sample = load_sample()
        tutor = SampleTutor(sample)
        scope = sample.scope

    start = SessionStart(
        format=SESSION_FORMAT, session_id=session_id, region=get_region().id, request=request, scope=scope, plan=tutor.plan()
    )
    _sessions[session_id] = Session(start=start, tutor=tutor, usage=usage, notes_name=notes_name, notes=notes)
    return start


@router.post("/{session_id}/next")
def next_part(session_id: str) -> NextReply:
    """The next part of the session, or `done` once there are no more."""
    session = _find(session_id)
    with session.lock:
        try:
            part = session.tutor.next_part(session.answers)
        except (LLMError, AgentError) as error:
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
        except (LLMError, AgentError) as error:
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
        request=session.start.request,
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
