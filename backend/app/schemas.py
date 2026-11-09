"""Request and response bodies for POST /api/command.

The frontend mirrors these as TypeScript types; change both sides together.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.actions import Action


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClickEvent(_Model):
    t: float  # seconds; for voice, relative to the start of recording
    structure_id: str


class SceneState(_Model):
    view: str | None = None
    visible_layers: list[str] = []
    highlighted: list[str] = []
    cross_section: str | None = None


class CommandRequest(_Model):
    session_id: str = Field(min_length=1)
    input_type: Literal["text", "voice"]
    text: str | None = None
    audio: str | None = None  # base64-encoded recording when input_type is "voice"
    click_events: list[ClickEvent] = []
    selection: list[str] = []  # structure IDs in the order they were selected
    toolbar_command: Literal["explain", "compare", "show_path", "isolate", "quiz"] | None = None
    scene_state: SceneState = SceneState()
    mode: Literal["explore", "quiz"] = "explore"

    @model_validator(mode="after")
    def needs_input(self) -> "CommandRequest":
        if self.input_type == "text" and not self.text and not self.toolbar_command:
            raise ValueError("text input needs text or a toolbar_command")
        if self.input_type == "voice" and not self.audio:
            raise ValueError("voice input needs audio")
        return self


class ResolvedRef(_Model):
    """One referring word in the command and the structures it was matched to.

    A list rather than a word -> ID map, so "compare this and this" can
    resolve each "this" separately. `start` is the word's character offset in
    the command text (or transcript), for linking the word to its chip.
    """

    word: str
    start: int = Field(ge=0)
    structure_ids: list[str] = Field(min_length=1)


class Citation(_Model):
    chunk_id: str
    section: str
    source_url: str


class WalkthroughStep(_Model):
    narration: str
    actions: list[Action] = []
    citations: list[str] = []  # chunk IDs


class Walkthrough(_Model):
    walkthrough_id: str
    title: str
    created_by: Literal["lumen", "external_agent"] = "lumen"
    steps: list[WalkthroughStep] = Field(min_length=1)


class CommandResponse(_Model):
    transcript: str | None = None
    resolved_refs: list[ResolvedRef] = []
    clarification: str | None = None  # when set, the other fields are empty
    answer: str | None = None
    citations: list[Citation] = []
    actions: list[Action] = []
    walkthrough: Walkthrough | None = None
