"""Scene actions: the contract between the agent and the browser.

The LLM's scene tools never run on the backend. Each call is parsed into one of
these models, checked against the registry, and sent to the browser in the
response's `actions` list, where the action executor runs it.

Validation happens in two steps:
1. Shape: Pydantic checks fields and types when the action is parsed.
2. References: `check_action` checks that every structure, view, layer,
   cross-section and path exists. Its error messages are written for the LLM
   to read and correct in the next round.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from app.registry import Registry

StructureIds = Annotated[list[str], Field(min_length=1)]


class _Action(BaseModel):
    # serialize_by_alias makes AnimatePathAction send "from", not "from_".
    model_config = ConfigDict(extra="forbid", validate_by_name=True, validate_by_alias=True, serialize_by_alias=True)


class HighlightAction(_Action):
    type: Literal["highlight"]
    structure_ids: StructureIds
    color: Literal["primary", "secondary", "correct", "wrong"] = "primary"
    exclusive: bool = False  # True clears other highlights first


class ClearHighlightsAction(_Action):
    type: Literal["clear_highlights"]


class IsolateAction(_Action):
    type: Literal["isolate"]
    structure_ids: StructureIds


class LabelAction(_Action):
    type: Literal["label"]
    structure_id: str
    text: str = Field(min_length=1, max_length=40)


class ClearLabelsAction(_Action):
    type: Literal["clear_labels"]


class SetViewAction(_Action):
    type: Literal["set_view"]
    view: str


class FocusAction(_Action):
    type: Literal["focus"]
    structure_id: str


class SetVisibilityAction(_Action):
    type: Literal["set_visibility"]
    structure_ids: list[str] = []
    layers: list[str] = []
    visible: bool

    @model_validator(mode="after")
    def needs_a_target(self) -> "SetVisibilityAction":
        if not self.structure_ids and not self.layers:
            raise ValueError("set_visibility needs structure_ids or layers")
        return self


class FadeOthersAction(_Action):
    type: Literal["fade_others"]
    structure_ids: StructureIds


class AnimatePathAction(_Action):
    type: Literal["animate_path"]
    path: str
    from_: str = Field(alias="from")
    to: str


class CrossSectionAction(_Action):
    type: Literal["cross_section"]
    section: str
    position: float = Field(ge=0, le=1)


class ClearCrossSectionAction(_Action):
    type: Literal["clear_cross_section"]


class AddNoteAction(_Action):
    type: Literal["add_note"]
    structure_id: str
    text: str = Field(min_length=1, max_length=280)
    author: Literal["agent"] = "agent"


class SetSelectionAction(_Action):
    type: Literal["set_selection"]
    structure_ids: list[str]


class ResetViewAction(_Action):
    type: Literal["reset_view"]


Action = Annotated[
    HighlightAction
    | ClearHighlightsAction
    | IsolateAction
    | LabelAction
    | ClearLabelsAction
    | SetViewAction
    | FocusAction
    | SetVisibilityAction
    | FadeOthersAction
    | AnimatePathAction
    | CrossSectionAction
    | ClearCrossSectionAction
    | AddNoteAction
    | SetSelectionAction
    | ResetViewAction,
    Field(discriminator="type"),
]

# Parses a plain dict into the right action model, chosen by its "type" field.
action_adapter: TypeAdapter[Action] = TypeAdapter(Action)


class ActionError(ValueError):
    """An action refers to something the registry doesn't have."""


def _structure_ids(action: _Action) -> list[str]:
    ids = list(getattr(action, "structure_ids", []))
    if hasattr(action, "structure_id"):
        ids.append(action.structure_id)
    if isinstance(action, AnimatePathAction):
        ids += [action.from_, action.to]
    return ids


def _check_name(kind: str, name: str, valid) -> None:
    if name not in valid:
        options = ", ".join(sorted(valid)) or "none are defined yet"
        raise ActionError(f"unknown {kind} {name!r}; valid {kind}s: {options}")


def check_action(action: _Action, registry: Registry) -> None:
    """Raise ActionError if the action refers to anything the registry lacks."""
    for structure_id in _structure_ids(action):
        if structure_id not in registry:
            raise ActionError(
                f"unknown structure id {structure_id!r}; use lookup_structure or list_structures to find valid IDs"
            )

    if isinstance(action, SetViewAction):
        _check_name("view", action.view, registry.views)
    elif isinstance(action, SetVisibilityAction):
        for layer in action.layers:
            _check_name("layer", layer, registry.layers)
    elif isinstance(action, CrossSectionAction):
        _check_name("cross-section", action.section, registry.cross_sections)
    elif isinstance(action, AnimatePathAction):
        _check_name("path", action.path, registry.paths)
        sequence = registry.paths[action.path].sequence
        for end in (action.from_, action.to):
            if end not in sequence:
                raise ActionError(f"{end!r} is not on path {action.path!r}")
        start, stop = sequence.index(action.from_), sequence.index(action.to)
        if start == stop:
            raise ActionError("from and to must be different structures")
        if start > stop:
            raise ActionError(
                f"on path {action.path!r}, {action.from_!r} comes after {action.to!r}; "
                f"use from={action.to!r}, to={action.from_!r}"
            )
