import copy

from scripts.validate_region import CenterlinesFile, StructuresFile, check, glb_bounds, main


def structure(structure_id, kind, parent="heart"):
    return {"id": structure_id, "name": structure_id, "side": None, "kind": kind, "parent": parent,
            "article": None, "z_anatomy_object": structure_id}


def piece(piece_id, points, radius=0.002, attach=None):
    length = sum(sum((b[i] - a[i]) ** 2 for i in range(3)) ** 0.5 for a, b in zip(points, points[1:]))
    return {"id": piece_id, "length": length, "attach": attach, "radius": [radius] * len(points), "points": points}


def mesh_node(name, index, low, high):
    return ({"name": name, "mesh": index},
            {"primitives": [{"attributes": {"POSITION": index}}]},
            {"min": list(low), "max": list(high)})


def tiny_region():
    """A chamber and an artery: a trunk along x with one branch going up from its middle."""
    structures = {
        "region": "test", "name": "Test", "source": "test", "units": "metres",
        "groups": [{"id": "heart", "name": "Heart", "parent": None, "article": "Heart"}],
        "structures": [structure("chamber", "surface"), structure("artery", "tube")],
        "landmarks": [{"id": "apex", "name": "Apex", "parent": "heart", "point": [0, 0, 0],
                       "nearest_structure": "chamber", "distance_to_surface": 0.03, "article": None}],
    }
    centerlines = {
        "region": "test", "source": "test", "units": "metres",
        "structures": {"artery": [
            piece("artery.0", [[0, 0, 0], [0.05, 0, 0], [0.1, 0, 0]]),
            piece("artery.1", [[0.05, 0, 0], [0.05, 0.03, 0]], attach={"piece": "artery.0", "at": 0.05, "gap": 0.0}),
        ]},
    }
    parts = [mesh_node("chamber", 0, (-0.05, -0.05, -0.05), (0, 0.05, 0.05)),
             mesh_node("artery", 1, (0, -0.002, -0.002), (0.1, 0.03, 0.002))]
    gltf = {"nodes": [p[0] for p in parts], "meshes": [p[1] for p in parts], "accessors": [p[2] for p in parts]}
    return structures, centerlines, gltf


def errors(structures, centerlines, gltf, article_keys=None):
    report = check(StructuresFile.model_validate(structures), CenterlinesFile.model_validate(centerlines), gltf, article_keys)
    return report.errors


def test_tiny_region_passes():
    assert errors(*tiny_region(), article_keys={"Heart"}) == []


def test_glb_bounds_reads_each_mesh_node():
    _, _, gltf = tiny_region()
    assert glb_bounds(gltf)["artery"] == ((0, -0.002, -0.002), (0.1, 0.03, 0.002))


def test_mesh_without_structure_and_structure_without_mesh():
    structures, centerlines, gltf = tiny_region()
    gltf["nodes"][0]["name"] = "ventricle"
    found = errors(structures, centerlines, gltf)
    assert any("'chamber' has no mesh" in e for e in found)
    assert any("'ventricle' in model.glb is not a structure" in e for e in found)


def test_vessel_without_centre_line():
    structures, centerlines, gltf = tiny_region()
    centerlines["structures"] = {}
    assert any("'artery' has no centre line" in e for e in errors(structures, centerlines, gltf))


def test_unknown_parent():
    structures, centerlines, gltf = tiny_region()
    structures["structures"][0]["parent"] = "lung"
    assert any("unknown parent 'lung'" in e for e in errors(structures, centerlines, gltf))


def test_branch_that_joins_nothing():
    structures, centerlines, gltf = tiny_region()
    centerlines["structures"]["artery"][1]["attach"] = None
    assert any("'artery.1' is not joined to anything" in e for e in errors(structures, centerlines, gltf))


def test_pieces_fanning_out_from_one_point_are_starting_points():
    structures, centerlines, gltf = tiny_region()
    fan = piece("artery.1", [[0, 0, 0], [0.05, 0.03, 0]])  # same start as artery.0, attached to nothing
    centerlines["structures"]["artery"][1] = fan
    assert errors(structures, centerlines, gltf) == []


def test_branch_joining_beyond_the_end_of_its_host():
    structures, centerlines, gltf = tiny_region()
    centerlines["structures"]["artery"][1]["attach"]["at"] = 0.5
    assert any("outside its length" in e for e in errors(structures, centerlines, gltf))


def test_attachment_loop():
    structures, centerlines, gltf = tiny_region()
    centerlines["structures"]["artery"][0]["attach"] = {"piece": "artery.1", "at": 0.01, "gap": 0.0}
    assert any("attachment loop" in e for e in errors(structures, centerlines, gltf))


def test_centre_line_in_the_wrong_frame():
    """Swapping two axes, as a Z-up export would, must not pass."""
    structures, centerlines, gltf = tiny_region()
    swapped = copy.deepcopy(centerlines)
    for p in swapped["structures"]["artery"]:
        p["points"] = [[x, z, y] for x, y, z in p["points"]]
    assert any("does not fit its mesh" in e for e in errors(structures, swapped, gltf))


def test_article_missing_from_the_articles_file():
    assert any("article 'Heart'" in e for e in errors(*tiny_region(), article_keys={"Lung"}))


def test_real_heart_export_passes(capsys):
    assert main([]) == 0
    assert "OK" in capsys.readouterr().out
