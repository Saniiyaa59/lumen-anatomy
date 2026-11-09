import copy

import pytest
from pydantic import ValidationError

from app.registry import Registry, RegistryFile, get_registry, normalize_name

# --- The real assets/structures.json ---------------------------------------


def test_real_registry_loads():
    registry = get_registry()
    assert registry.organ == "heart"
    assert "left_ventricle" in registry


def test_get_by_id():
    assert get_registry().get("left_ventricle").display_name == "Left ventricle"


def test_get_unknown_id_raises():
    with pytest.raises(KeyError, match="spleen"):
        get_registry().get("spleen")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Left ventricle", "left_ventricle"),
        ("the LEFT  ventricle", "left_ventricle"),
        ("left_ventricle", "left_ventricle"),
        ("LV", "left_ventricle"),
        ("bicuspid valve", "mitral_valve"),
        ("LAD", "anterior_interventricular_artery"),
    ],
)
def test_find_by_name_or_alias(name, expected):
    assert get_registry().find(name).id == expected


def test_find_unknown_name_returns_none():
    assert get_registry().find("spleen") is None


def test_structure_for_mesh():
    registry = get_registry()
    assert registry.structure_for_mesh("Aortic_arch") == "aorta"
    assert registry.structure_for_mesh("Aortic_left_coronary_leaflet") == "aortic_valve"
    assert registry.structure_for_mesh("Not_a_mesh") is None


def test_list_by_group():
    valves = {s.id for s in get_registry().list(group="valve")}
    assert valves == {"tricuspid_valve", "mitral_valve", "pulmonary_valve", "aortic_valve"}


def test_normalize_name():
    assert normalize_name("  The Right-Atrium ") == "right atrium"
    assert normalize_name("the") == "the"


# --- Validation, using a small two-structure registry ----------------------

VALID = {
    "organ": "heart",
    "structures": [
        {
            "id": "left_atrium",
            "display_name": "Left atrium",
            "mesh_names": ["Left_atrium"],
            "aliases": ["LA"],
            "group": "chamber",
            "layer": "chambers",
            "size_class": "large",
            "neighbors": ["mitral_valve"],
            "short_description": "Receives blood from the lungs.",
        },
        {
            "id": "mitral_valve",
            "display_name": "Mitral valve",
            "mesh_names": ["Mitral_posterior_leaflet"],
            "group": "valve",
            "layer": "valves",
            "size_class": "small",
            "neighbors": ["left_atrium"],
            "short_description": "Between the left atrium and left ventricle.",
        },
    ],
}


def make(edit):
    """Copy VALID, apply an edit function to the copy and return it."""
    data = copy.deepcopy(VALID)
    edit(data)
    return data


def test_valid_example_loads():
    registry = Registry(RegistryFile.model_validate(VALID))
    assert registry.ids() == ["left_atrium", "mitral_valve"]


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (lambda d: d["structures"][1].update(id="left_atrium"), "duplicate structure ids"),
        (lambda d: d["structures"][1].update(mesh_names=["Left_atrium"]), "used by both"),
        (lambda d: d["structures"][0].update(neighbors=["mitral_valve", "aorta"]), "unknown neighbor"),
        (lambda d: d["structures"][1].update(neighbors=[]), "not the other way round"),
        (lambda d: d["structures"][0]["neighbors"].append("left_atrium"), "itself"),
        (lambda d: d["structures"][1].update(aliases=["la"]), "matches both"),
        (lambda d: d["structures"][0].update(best_view="anterior"), "unknown best_view"),
        (lambda d: d.update(paths={"flow": {"sequence": ["left_atrium", "aorta"]}}), "unknown structures"),
        (lambda d: d["structures"][0].update(id="Left Atrium"), "pattern"),
        (lambda d: d["structures"][0].update(size_class="huge"), "size_class"),
        (lambda d: d["structures"][0].update(neighbours=[]), "neighbours"),
    ],
    ids=[
        "duplicate-id",
        "mesh-used-twice",
        "unknown-neighbor",
        "one-way-neighbor",
        "self-neighbor",
        "alias-collision",
        "unknown-view",
        "unknown-path-structure",
        "bad-id-format",
        "bad-size-class",
        "misspelled-field",
    ],
)
def test_invalid_registry_is_rejected(edit, message):
    with pytest.raises(ValidationError, match=message):
        RegistryFile.model_validate(make(edit))
