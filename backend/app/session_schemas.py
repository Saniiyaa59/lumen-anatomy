"""The study-session format, as sent to and received from the browser.

Described field by field in docs/session_format.md. The frontend holds the same
shape as TypeScript types and its own check (frontend/src/session/format.ts);
change all three together. The sample session in assets/fixtures/sessions/ is
tested against both sides, so they cannot drift apart unnoticed.

These models check shape only. Whether an id or a distance exists on the 3D
model is checked in the browser, which has the model loaded.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SESSION_FORMAT = "lumen.session/0.1"

Text = Annotated[str, Field(min_length=1)]
Link = Annotated[str, Field(pattern=r"^https?://")]
PartKind = Literal["demonstration", "pulse", "damage_slider", "click_case"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# Where a fact came from. Every piece of text the student reads has one.


class NotesSource(_Model):
    type: Literal["notes"]
    file: Text
    page: int = Field(ge=1)


class AtlasSource(_Model):
    type: Literal["atlas"]
    article: Text  # a key in assets/text/z_anatomy_articles.jsonl
    url: Link | None


class WebSource(_Model):
    type: Literal["web"]
    title: Text
    url: Link


class ModelSource(_Model):
    """Measured on the 3D model itself, e.g. a length."""

    type: Literal["model"]


Source = Annotated[NotesSource | AtlasSource | WebSource | ModelSource, Field(discriminator="type")]


class Statement(_Model):
    text: Text
    source: Source


class Place(_Model):
    """A point on a vessel: a centre-line piece and a distance along it, in metres."""

    piece: Text
    at: float = Field(ge=0)


class Region(_Model):
    """A stretch of one centre-line piece. The JSON field names are `from` and `to`."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    piece: Text
    start: float = Field(ge=0, alias="from")
    to: float

    @model_validator(mode="after")
    def runs_forwards(self) -> "Region":
        if self.start >= self.to:
            raise ValueError(f"from {self.start} to {self.to} is not a stretch: `from` must be less than `to`")
        return self


class View(_Model):
    """What the camera should show. The viewer works out the camera position."""

    look_at: list[Text] = Field(min_length=1)
    side: Literal["anterior", "posterior", "left", "right", "superior", "inferior"] | None


class Target(_Model):
    """Where a click counts: stretches of vessel and/or whole structures."""

    regions: list[Region]
    structures: list[Text]

    @model_validator(mode="after")
    def names_something(self) -> "Target":
        if not self.regions and not self.structures:
            raise ValueError("must name at least one stretch of vessel or one structure")
        return self


# Parts. Each has a view, what to hide and what to read; each kind adds its own fields.


class _Part(_Model):
    id: Text
    title: Text
    view: View
    hide: list[Text]  # structure ids, or group ids to hide everything in a group
    statements: list[Statement]


class Demonstration(_Part):
    kind: Literal["demonstration"]
    highlight: list[Text]
    statements: list[Statement] = Field(min_length=1)


class Pulse(_Part):
    """A pulse runs from `from` to `to`; with no end it spreads into every branch beyond the start."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    kind: Literal["pulse"]
    start: Place = Field(alias="from")
    to: Place | None


class Zone(_Model):
    regions: list[Region] = Field(min_length=1)
    statement: Statement


class DamageSlider(_Part):
    """The student drags a damage point along `track`; everything beyond it greys out."""

    kind: Literal["damage_slider"]
    track: Region
    start_at: float
    zones: list[Zone]

    @model_validator(mode="after")
    def starts_on_track(self) -> "DamageSlider":
        if not self.track.start <= self.start_at <= self.track.to:
            raise ValueError(f"start_at {self.start_at} is outside the track ({self.track.start} to {self.track.to})")
        return self


class Answer(Target):
    tolerance: float = Field(ge=0)  # how far past the end of a region a click still counts, in metres


class NearMiss(Target):
    statement: Statement


class Feedback(_Model):
    correct: Statement
    wrong: Statement
    near_misses: list[NearMiss]


class ClickCase(_Part):
    """A short patient story; the student clicks where the problem is."""

    kind: Literal["click_case"]
    story: Text  # an invented patient, so it has no source
    question: Text
    answer: Answer
    feedback: Feedback

    @model_validator(mode="after")
    def near_misses_are_wrong(self) -> "ClickCase":
        for index, miss in enumerate(self.feedback.near_misses):
            shares_structure = set(miss.structures) & set(self.answer.structures)
            overlaps = any(
                a.piece == b.piece and a.start < b.to and b.start < a.to for a in miss.regions for b in self.answer.regions
            )
            if shares_structure or overlaps:
                raise ValueError(f"near miss {index} overlaps the correct answer")
        return self


Part = Annotated[Demonstration | Pulse | DamageSlider | ClickCase, Field(discriminator="kind")]


class PlanItem(_Model):
    part_id: Text
    title: Text
    kind: PartKind


class Scope(_Model):
    """What the agent can show on the model and what it can only explain in words."""

    can_show: list[Text]
    words_only: list[Text]


class Summary(_Model):
    solid: list[Text]
    shaky: list[Text]
    sources: list[Source]


class OpeningAnswer(_Model):
    """The tutor's answer when the student's first message was a question rather than a request for a session."""

    statements: list[Statement] = Field(min_length=1)
    point_to: list[str]


class _Opening(_Model):
    """What a session opens with: shared by the backend's first reply and a recorded session."""

    format: Literal["lumen.session/0.1"]
    session_id: Text
    region: Text
    request: Text
    scope: Scope
    plan: list[PlanItem]


class SessionStart(_Opening):
    """The backend's first reply: what it understood and what it plans.

    An empty plan means the student is exploring: they ask about what they select
    with /chat, and the tutor adds a plan only if they ask for one. `answer` is
    the tutor's answer when their first message was a question; it is left out otherwise.
    """

    answer: OpeningAnswer | None = None


class Question(_Model):
    """A question the tutor asks the student before it plans, when it can't tell what to cover."""

    text: Text
    options: list[Text] = Field(default_factory=list, max_length=4)  # answers the student can pick with one click


class TutorQuestion(_Model):
    """The backend's first reply when the tutor needs to ask something before planning.

    The student answers with POST /api/sessions/{id}/reply. The reply to that is
    either another TutorQuestion or a SessionStart with the plan.
    """

    format: Literal["lumen.session/0.1"]
    session_id: Text
    region: Text
    request: Text
    question: Question


class ReplyRequest(_Model):
    text: Text  # what the student typed or picked


class ChatRequest(_Model):
    """Something the student says during a session."""

    text: Text
    selected: list[str] = Field(default_factory=list)  # structure ids selected on the model, so "this" can be understood
    part_id: str | None = None  # the part on screen, if any


class ChatReply(_Model):
    statements: list[Statement] = Field(min_length=1)  # the tutor's answer, each with its source
    point_to: list[str]  # structure ids the browser should select so the student sees what is meant
    plan: list[PlanItem]  # the current plan, which the tutor may have changed
    plan_changed: bool


class RecordedSession(_Opening):
    """A whole session in one file: the start, every part and the summary."""

    parts: list[Part]
    summary: Summary

    @model_validator(mode="after")
    def plan_matches_parts(self) -> "RecordedSession":
        if not self.plan:
            raise ValueError("a recorded session needs a plan with at least one item")
        kinds: dict[str, str] = {}
        for part in self.parts:
            if part.id in kinds:
                raise ValueError(f"part id {part.id!r} is used by more than one part")
            kinds[part.id] = part.kind
        for item in self.plan:
            if item.part_id not in kinds:
                raise ValueError(f"plan item {item.part_id!r} is not the id of a part")
            if item.kind != kinds[item.part_id]:
                raise ValueError(f"plan item {item.part_id!r} says {item.kind!r} but the part is a {kinds[item.part_id]!r}")
        return self


# What the browser sends.


class NotesUpload(_Model):
    filename: Text
    data: Text  # the PDF, base64-encoded


class StartRequest(_Model):
    request: str = ""  # what the student asked; empty to just explore the model
    notes: NotesUpload | None = None


class ClickAnswer(_Model):
    """One click on a case, already graded by the browser."""

    part_id: Text
    attempt: int = Field(ge=1)
    structure_id: Text
    point: tuple[float, float, float]  # the exact point, in the model's frame
    piece: Text | None  # for a vessel, where on it; both null otherwise
    at: float | None
    correct: bool
    seconds: float = Field(ge=0)  # from the case appearing to the click

    @model_validator(mode="after")
    def place_is_whole(self) -> "ClickAnswer":
        if (self.piece is None) != (self.at is None):
            raise ValueError("piece and at must both be given or both be null")
        return self


# Replies that are not part of a recorded session.


class NextReply(_Model):
    part: Part | None  # null once every part has been sent
    plan: list[PlanItem]
    done: bool


class AnswerReply(_Model):
    plan: list[PlanItem]  # the current plan; the agent may have changed it


class Timing(_Model):
    """One request to Claude: how long it took and what came of it."""

    at: float  # unix time the reply came, so builders running side by side can be lined up
    stage: str  # the task: "plan", "part <id>", "chat", "decide after <id>", "summary" or "notes"
    claude_seconds: float  # waiting for Claude
    here_seconds: float  # the backend's own work on the reply: lookups, checking a hand-in
    did: str  # what the reply was: lookups and which, a hand-in accepted or rejected, or text
    output_tokens: int  # thinking included
    input_tokens: int
    cached_share: float  # of the input, the share read from the cache


class SessionState(_Model):
    """What the backend holds for one session. For checking and debugging, not for the student."""

    session_id: str
    request: str
    conversation: list[str]  # what the tutor asked and the student replied before the plan, in order
    source: Literal["sample", "agent"]  # where its parts come from
    notes: str | None  # the uploaded file's name
    notes_bytes: int
    parts_sent: int
    finished: bool
    answers: list[ClickAnswer]
    dropped: list[str]  # parts the agent gave up on, with the reason
    # What the session has cost so far, when the agent built it.
    claude_calls: int
    input_tokens: int
    output_tokens: int
    claude_seconds: float  # waiting for Claude, summed; builders run side by side, so more than the time that passed
    timings: list[Timing]  # the latest requests, oldest first
