import json
import struct

import pytest

from app.registry import Registry, RegistryFile, get_registry
from scripts.validate_glb import DEFAULT_GLB, compare, main, read_glb_mesh_names


def write_glb(path, gltf):
    """Write a minimal GLB: header plus a JSON chunk, no geometry."""
    body = json.dumps(gltf).encode()
    body += b" " * (-len(body) % 4)  # chunks are padded to 4 bytes
    header = struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(body))
    path.write_bytes(header + struct.pack("<I4s", len(body), b"JSON") + body)


def test_reads_names_of_nodes_with_meshes(tmp_path):
    glb = tmp_path / "test.glb"
    write_glb(glb, {"nodes": [
        {"name": "Left_atrium", "mesh": 0},
        {"name": "Scene_root"},  # no mesh: not clickable, so ignored
        {"name": "Mitral_posterior_leaflet", "mesh": 1},
    ]})
    assert read_glb_mesh_names(glb) == {"Left_atrium", "Mitral_posterior_leaflet"}


def test_rejects_non_glb_file(tmp_path):
    not_glb = tmp_path / "heart.obj"
    not_glb.write_bytes(b"o Heart\nv 0 0 0\n" + b"\0" * 20)
    with pytest.raises(ValueError, match="not a GLB"):
        read_glb_mesh_names(not_glb)


def test_compare_reports_both_directions():
    registry = Registry(RegistryFile.model_validate({
        "organ": "heart",
        "structures": [{
            "id": "aorta",
            "display_name": "Aorta",
            "mesh_names": ["Ascending_aorta", "Aortic_arch"],
            "group": "great_vessel",
            "layer": "great_vessels",
            "size_class": "large",
            "short_description": "Main artery.",
        }],
    }))
    missing, unused = compare({"Ascending_aorta", "Superior_vena_cava"}, registry)
    assert missing == ["Aortic_arch"]
    assert unused == ["Superior_vena_cava"]


def test_real_model_matches_real_registry():
    assert compare(read_glb_mesh_names(DEFAULT_GLB), get_registry()) == ([], [])


def test_main_exits_zero_on_real_files(capsys):
    assert main([]) == 0
    assert "OK" in capsys.readouterr().out
