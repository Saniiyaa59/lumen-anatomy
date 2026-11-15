"""Check a region exported by backend/scripts/export_region.py.

Confirms that the shapes, the structure list and the centre lines agree:
every mesh in model.glb is a structure and the other way round, every vessel
has a centre line that lies inside its own tube, and every branch joins the
vessel it comes off. Exits with status 1 if anything is wrong.

Run from backend/ with the venv active:

    python -m scripts.validate_region
    python -m scripts.validate_region --region ../assets/regions/heart
"""

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from app.config import REPO_ROOT
from app.region import ID_PATTERN, CenterlinesFile, Point, StructuresFile
from scripts.validate_glb import read_glb_json

DEFAULT_REGION = REPO_ROOT / "assets" / "regions" / "heart"
DEFAULT_ARTICLES = REPO_ROOT / "assets" / "text" / "z_anatomy_articles.jsonl"

TOLERANCE = 0.001  # metres
ON_SURFACE = 0.002  # metres; a landmark this close to a structure counts as touching it

__all__ = ["ID_PATTERN", "CenterlinesFile", "StructuresFile"]


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def glb_bounds(gltf: dict) -> dict[str, tuple[Point, Point]]:
    """Bounding box of each named mesh node, from the min/max every glTF position list carries."""
    bounds = {}
    for node in gltf.get("nodes", []):
        if "mesh" not in node or "name" not in node:
            continue
        if any(key in node for key in ("translation", "rotation", "scale", "matrix")):
            raise ValueError(f"node {node['name']!r} is moved or scaled; the export should bake that into the mesh")
        lows, highs = [], []
        for primitive in gltf["meshes"][node["mesh"]]["primitives"]:
            accessor = gltf["accessors"][primitive["attributes"]["POSITION"]]
            lows.append(accessor["min"])
            highs.append(accessor["max"])
        bounds[node["name"]] = (tuple(map(min, zip(*lows))), tuple(map(max, zip(*highs))))
    return bounds


def path_length(points: list[Point]) -> float:
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def check(structures: StructuresFile, centerlines: CenterlinesFile, gltf: dict, article_keys: set[str] | None) -> Report:
    report = Report()
    error = report.errors.append

    # Ids are unique across groups, structures and landmarks, and parents exist.
    entries = [*structures.groups, *structures.structures, *structures.landmarks]
    ids = [e.id for e in entries]
    for duplicate in sorted({i for i in ids if ids.count(i) > 1}):
        error(f"id {duplicate!r} is used more than once")
    parent_of = {e.id: e.parent for e in entries}
    can_be_parent = {e.id for e in [*structures.groups, *structures.structures]}
    for e in entries:
        if e.parent is not None and e.parent not in can_be_parent:
            error(f"{e.id!r} has unknown parent {e.parent!r}")
        seen, current = set(), e.id
        while current is not None and current in parent_of:
            if current in seen:
                error(f"{e.id!r} is in a parent loop")
                break
            seen.add(current)
            current = parent_of[current]

    # Shapes and structures match one to one.
    bounds = glb_bounds(gltf)
    by_id = {s.id: s for s in structures.structures}
    for missing in sorted(by_id.keys() - bounds.keys()):
        error(f"structure {missing!r} has no mesh in model.glb")
    for unused in sorted(bounds.keys() - by_id.keys()):
        error(f"mesh {unused!r} in model.glb is not a structure")

    # Every vessel has a centre line, and nothing else does.
    tubes = {s.id for s in structures.structures if s.kind == "tube"}
    for missing in sorted(tubes - centerlines.structures.keys()):
        error(f"vessel {missing!r} has no centre line")
    for unknown in sorted(centerlines.structures.keys() - tubes):
        error(f"centre line for {unknown!r}, which is not a vessel in structures.json")

    pieces = {p.id: (structure_id, p) for structure_id, ps in centerlines.structures.items() for p in ps}
    if len(pieces) != sum(len(ps) for ps in centerlines.structures.values()):
        error("two centre-line pieces share an id")

    for structure_id, structure_pieces in centerlines.structures.items():
        if not structure_pieces:
            error(f"vessel {structure_id!r} has an empty centre line")
            continue
        for p in structure_pieces:
            if len(p.points) < 2 or len(p.radius) != len(p.points):
                error(f"piece {p.id!r} needs at least two points and one radius per point")
                continue
            if min(p.radius) <= 0:
                error(f"piece {p.id!r} has a radius of zero or less")
            if p.length <= 0 or abs(path_length(p.points) - p.length) > max(TOLERANCE, 0.01 * p.length):
                error(f"piece {p.id!r} says it is {p.length} m long but its points measure {path_length(p.points):.5f} m")

        # The centre line must lie inside its own tube: this catches a wrong axis or unit.
        if structure_id in bounds:
            low, high = bounds[structure_id]
            points = [pt for p in structure_pieces for pt in p.points]
            widest = max(r for p in structure_pieces for r in p.radius)
            for axis in range(3):
                line_low, line_high = min(pt[axis] for pt in points), max(pt[axis] for pt in points)
                outside = line_low < low[axis] - TOLERANCE or line_high > high[axis] + TOLERANCE
                too_small = line_low - widest > low[axis] + TOLERANCE or line_high + widest < high[axis] - TOLERANCE
                if outside or too_small:
                    error(f"centre line of {structure_id!r} does not fit its mesh on axis {'xyz'[axis]}")
                    break

    # Branches: each joins a real piece, at a place on that piece, with no loops.
    for piece_id, (_, p) in pieces.items():
        if p.attach is None:
            continue
        if p.attach.piece == piece_id or p.attach.piece not in pieces:
            error(f"piece {piece_id!r} is attached to {p.attach.piece!r}, which is not another piece")
            continue
        host = pieces[p.attach.piece][1]
        if not 0 < p.attach.at <= host.length + TOLERANCE:
            error(f"piece {piece_id!r} joins {host.id!r} at {p.attach.at} m, outside its length of {host.length} m")
        if p.attach.gap > max(host.radius, default=0) + TOLERANCE:
            error(f"piece {piece_id!r} starts {p.attach.gap} m from {host.id!r}, further than that vessel is wide")
        seen, current = {piece_id}, p.attach.piece
        while current in pieces and pieces[current][1].attach is not None:
            if current in seen:
                error(f"piece {piece_id!r} is in an attachment loop")
                break
            seen.add(current)
            current = pieces[current][1].attach.piece

    # A piece attached to nothing must start a vessel, or fan out from the same point as one that does.
    roots = []
    for structure_id, structure_pieces in centerlines.structures.items():
        loose = [p for p in structure_pieces if p.attach is None and len(p.points) >= 2]
        for p in loose:
            shares_start = any(o is not p and math.dist(o.points[0], p.points[0]) <= TOLERANCE for o in loose)
            if p is structure_pieces[0] or shares_start:
                roots.append(p.id)
            else:
                error(f"piece {p.id!r} is not joined to anything")

    if article_keys is not None:
        for e in entries:
            if e.article is not None and e.article not in article_keys:
                error(f"{e.id!r} points to article {e.article!r}, which is not in the articles file")

    with_article = sum(1 for s in structures.structures if s.article)
    touching = [m for m in structures.landmarks if m.distance_to_surface is not None and m.distance_to_surface <= ON_SURFACE]
    report.notes += [
        f"{len(structures.structures)} structures ({len(tubes)} vessels), {len(structures.groups)} groups, {len(bounds)} meshes",
        f"{len(pieces)} centre-line pieces: {len(pieces) - len(roots)} joined to another piece, {len(roots)} starting points",
        f"{with_article} of {len(structures.structures)} structures have an article under their own name",
        f"{len(touching)} of {len(structures.landmarks)} landmarks touch a structure (within {ON_SURFACE * 1000:.0f} mm)",
    ]
    return report


def read_article_keys(path: Path) -> set[str]:
    with path.open(encoding="utf-8") as f:
        return {json.loads(line)["key"] for line in f if line.strip()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--region", type=Path, default=DEFAULT_REGION, help="folder holding the exported files")
    parser.add_argument("--articles", type=Path, default=DEFAULT_ARTICLES)
    args = parser.parse_args(argv)

    try:
        structures = StructuresFile.model_validate_json((args.region / "structures.json").read_text(encoding="utf-8"))
        centerlines = CenterlinesFile.model_validate_json((args.region / "centerlines.json").read_text(encoding="utf-8"))
    except ValidationError as error:
        print(f"{args.region} has a file in the wrong format:\n{error}")
        return 1
    article_keys = read_article_keys(args.articles) if args.articles.exists() else None
    report = check(structures, centerlines, read_glb_json(args.region / "model.glb"), article_keys)

    print(f"Region {structures.region!r} in {args.region}")
    for note in report.notes:
        print(f"  {note}")
    if article_keys is None:
        print(f"  articles not checked: {args.articles} not found")
    for problem in report.errors:
        print(f"  ERROR: {problem}")
    if report.errors:
        return 1
    print("OK: shapes, structures and centre lines agree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
