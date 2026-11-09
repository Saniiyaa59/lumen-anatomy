import pytest
from pydantic import ValidationError

from app.actions import ActionError, AnimatePathAction, HighlightAction, action_adapter, check_action
from app.registry import Registry, RegistryFile, get_registry


def parse(data):
    return action_adapter.validate_python(data)


# --- Shape --------------------------------------------------------------------


def test_type_field_picks_the_model():
    action = parse({"type": "highlight", "structure_ids": ["left_ventricle"]})
    assert isinstance(action, HighlightAction)
    assert action.color == "primary"
    assert action.exclusive is False


def test_animate_path_uses_from_on_the_wire():
    action = parse({"type": "animate_path", "path": "blood_flow", "from": "right_atrium", "to": "aorta"})
    assert isinstance(action, AnimatePathAction)
    assert action.from_ == "right_atrium"
    assert action.model_dump()["from"] == "right_atrium"


@pytest.mark.parametrize(
    "data",
    [
        {"type": "explode", "structure_ids": ["aorta"]},  # unknown type
        {"type": "highlight", "structure_ids": []},  # empty list
        {"type": "highlight", "structure_ids": ["aorta"], "color": "purple"},
        {"type": "highlight", "structure_ids": ["aorta"], "blink": True},  # unknown field
        {"type": "label", "structure_id": "aorta", "text": "x" * 41},  # over 40 chars
        {"type": "set_visibility", "visible": False},  # no target
        {"type": "cross_section", "section": "four_chamber", "position": 1.5},
    ],
    ids=["unknown-type", "empty-ids", "bad-color", "unknown-field", "long-label", "no-target", "position-range"],
)
def test_bad_shapes_are_rejected(data):
    with pytest.raises(ValidationError):
        parse(data)


# --- References ---------------------------------------------------------------

REGISTRY = Registry(RegistryFile.model_validate({
    "organ": "heart",
    "structures": [
        {"id": s, "display_name": s, "mesh_names": [s], "group": "g", "layer": "chambers",
         "size_class": "large", "short_description": "."}
        for s in ["right_atrium", "right_ventricle", "aorta", "left_atrium"]
    ],
    "views": {"anterior": {"position": [0, 0, 3], "target": [0, 0, 0]}},
    "paths": {"flow": {"sequence": ["right_atrium", "right_ventricle", "aorta"]}},
}))


def check(data):
    check_action(parse(data), REGISTRY)


def test_valid_actions_pass():
    check({"type": "highlight", "structure_ids": ["aorta"]})
    check({"type": "set_view", "view": "anterior"})
    check({"type": "set_visibility", "layers": ["chambers"], "visible": False})
    check({"type": "animate_path", "path": "flow", "from": "right_atrium", "to": "aorta"})


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"type": "focus", "structure_id": "spleen"}, "unknown structure id 'spleen'"),
        ({"type": "set_view", "view": "top"}, "valid views: anterior"),
        ({"type": "set_visibility", "layers": ["bones"], "visible": True}, "unknown layer"),
        ({"type": "cross_section", "section": "four_chamber", "position": 0.5}, "none are defined yet"),
        ({"type": "animate_path", "path": "lymph", "from": "aorta", "to": "aorta"}, "unknown path"),
        ({"type": "animate_path", "path": "flow", "from": "left_atrium", "to": "aorta"}, "not on path"),
        ({"type": "animate_path", "path": "flow", "from": "aorta", "to": "right_atrium"}, "use from='right_atrium'"),
        ({"type": "animate_path", "path": "flow", "from": "aorta", "to": "aorta"}, "must be different"),
    ],
)
def test_bad_references_explain_the_fix(data, message):
    with pytest.raises(ActionError, match=message):
        check(data)


def test_real_registry_lists_layers():
    assert get_registry().layers == ["chambers", "coronary_vessels", "great_vessels", "valves"]
