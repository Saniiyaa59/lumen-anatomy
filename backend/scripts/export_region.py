"""Export one region of the Z-Anatomy atlas for Lumen.

Runs inside Blender, not the backend venv. See docs/asset_prep.md:

    blender --background --factory-startup --disable-autoexec <path>/Z-Anatomy/Startup.blend \
        --python backend/scripts/export_region.py -- assets/regions/heart/region.json \
        [--articles assets/text/z_anatomy_articles.jsonl]

The region file names Z-Anatomy objects only: `roots` (each root and everything
under it) and `extra_objects` (that object alone). Everything else is read from
the atlas, nothing is written by hand:

    model.glb         one mesh per structure, named by structure id
    structures.json   structures, the groups above them, and labelled landmarks
    centerlines.json  the path down the middle of every vessel, with branch points

`--articles` also writes every description article in the atlas (all regions).

Coordinates in the JSON files use the same frame as the GLB: metres, +Y up
(Blender's x, y, z becomes x, z, -y).
"""

import argparse
import json
import re
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import interpolate_bezier

# Z-Anatomy marks what an object is with a suffix on its name.
SUFFIX = re.compile(r"\.(l|r|g|j|t|s|i|ol|or|el|er|st)$")
GROUP = {"g"}  # a named group; its children are its members
LANDMARK_LABEL = {"t", "s"}  # a text label for a named place on a structure
LABEL_LINE = {"j", "i"}  # the two-point line from a label to the place it names
SIDE = {"l": "left", "r": "right"}

# Text blocks that are the atlas' own bookkeeping, not articles.
NOT_AN_ARTICLE = re.compile(r"^(Translations|obj_list|text_list|SHEET_.*|List_.*|Wiki (Phrases|Results)|1\.Licence|.*\.py|z-script.*)$")
TRAILING_URL = re.compile(r"https?://\S+$")

JOIN_TOLERANCE = 0.001  # metres; a branch that starts this close to another vessel's path joins it


def split_name(name: str) -> tuple[str, str | None]:
    """'Brachial artery.l' -> ('Brachial artery', 'l'); 'Heart.g' -> ('Heart', 'g')."""
    match = SUFFIX.search(name)
    return (name[: match.start()], match.group(1)) if match else (name, None)


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return s if not s or s[0].isalpha() else f"x_{s}"


def to_gltf(v: Vector) -> list[float]:
    """Blender (x, y, z) to the GLB's frame, rounded to 0.01 mm."""
    return [round(v.x, 5), round(v.z, 5), round(-v.y, 5)]


class IdMaker:
    """Stable, unique ids made from Z-Anatomy names."""

    def __init__(self):
        self.used: set[str] = set()

    def make(self, text: str, fallback: str) -> str:
        base = slug(text) or f"unnamed_{slug(fallback)}"
        candidate, n = base, 2
        while candidate in self.used:
            candidate, n = f"{base}_{n}", n + 1
        self.used.add(candidate)
        return candidate


def collect(region: dict) -> list[bpy.types.Object]:
    """The region's objects: every root with all its descendants, plus the extras."""
    missing = [n for n in region["roots"] + region.get("extra_objects", []) if n not in bpy.data.objects]
    if missing:
        sys.exit(f"Objects not found in the .blend file: {missing}")
    found: dict[str, bpy.types.Object] = {}
    for name in region["roots"]:
        root = bpy.data.objects[name]
        for obj in [root, *root.children_recursive]:
            found[obj.name] = obj
    for name in region.get("extra_objects", []):
        found[name] = bpy.data.objects[name]
    return sorted(found.values(), key=lambda o: o.name)


def bake(source: bpy.types.Object, name: str, depsgraph) -> bpy.types.Mesh:
    """A plain world-space mesh of `source`: modifiers applied, curves turned into tubes."""
    mesh = bpy.data.meshes.new_from_object(source.evaluated_get(depsgraph), depsgraph=depsgraph)
    mesh.transform(source.matrix_world)
    mesh.materials.clear()
    mesh.name = name
    return mesh


def sample_spline(obj: bpy.types.Object, spline) -> tuple[list[Vector], list[float]]:
    """World-space points along a spline's path and the tube radius at each."""
    curve = obj.data
    world = obj.matrix_world
    scale = sum(world.to_scale()) / 3
    points: list[Vector] = []
    radii: list[float] = []
    if spline.type == "BEZIER":
        knots = list(spline.bezier_points)
        steps = max(curve.resolution_u, 1)
        for a, b in zip(knots, knots[1:]):
            segment = interpolate_bezier(a.co, a.handle_right, b.handle_left, b.co, steps + 1)
            for k, co in enumerate(segment[:-1]):
                points.append(world @ co)
                radii.append(a.radius + (b.radius - a.radius) * k / steps)
        points.append(world @ knots[-1].co)
        radii.append(knots[-1].radius)
    else:  # POLY and NURBS: the control points are the best available path
        for pt in spline.points:
            points.append(world @ Vector(pt.co[:3]))
            radii.append(pt.radius)
    return points, [r * curve.bevel_depth * scale for r in radii]


def nearest_on_path(point: Vector, path: list[Vector], lengths: list[float]) -> tuple[float, float, int, float]:
    """Closest point on a path: (distance, distance along the path, segment index, position in segment)."""
    best = (float("inf"), 0.0, 0, 0.0)
    for i in range(len(path) - 1):
        a, ab = path[i], path[i + 1] - path[i]
        t = 0.0 if ab.length_squared == 0 else max(0.0, min(1.0, (point - a).dot(ab) / ab.length_squared))
        distance = (point - (a + ab * t)).length
        if distance < best[0]:
            best = (distance, lengths[i] + ab.length * t, i, t)
    return best


def top_ancestor(obj: bpy.types.Object) -> str:
    while obj.parent:
        obj = obj.parent
    return obj.name


def find_attachments(pieces: list[dict]) -> None:
    """Work out where each piece of a vessel branches off another piece.

    A piece joins the path it starts on (within JOIN_TOLERANCE). Failing that it
    joins a vessel whose wall it starts on, such as a coronary artery leaving the
    aorta. Pieces that only share a starting point are siblings, not parent and child.
    Arteries and veins are kept apart: they run side by side without joining.
    """
    for piece in pieces:
        start = piece["path"][0]
        exact, wall = [], []
        for other in pieces:
            if other is piece or other["system"] != piece["system"]:
                continue
            distance, along, i, t = nearest_on_path(start, other["path"], other["lengths"])
            if along <= JOIN_TOLERANCE:
                continue
            radius = other["radii"][i] + (other["radii"][i + 1] - other["radii"][i]) * t
            related = other["object"] in (piece["object"], piece["parent_object"])
            if distance <= JOIN_TOLERANCE:
                exact.append((not related, distance, other, along))
            elif distance <= radius + JOIN_TOLERANCE:
                wall.append((not related, distance - radius, distance, other, along))
        # Where two vessels qualify, trust the atlas' own parent before the nearer stranger.
        chosen = min(exact, key=lambda c: c[:2]) if exact else min(wall, key=lambda c: c[:3]) if wall else None
        piece["attach"] = None
        if chosen:
            distance, other, along = chosen[-3:]
            piece["attach"] = {"piece": other["id"], "at": round(along, 5), "gap": round(distance, 5)}


def write_json(path: Path, data: dict) -> None:
    """Indented JSON, with each list of numbers kept on one line."""
    text = json.dumps(data, indent=2, ensure_ascii=False)
    text = re.sub(r"\[\s+(-?[\d.e-]+(?:,\s+-?[\d.e-]+)*)\s+\]", lambda m: "[" + re.sub(r"\s+", " ", m.group(1)) + "]", text)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def export_articles(path: Path) -> None:
    """Write every description article in the atlas, one JSON object per line."""
    bodies: dict[str, str] = {}
    lines = []
    for text in sorted(bpy.data.texts, key=lambda t: t.name):
        raw = text.as_string().strip()
        if not raw or NOT_AN_ARTICLE.match(text.name):
            continue
        if raw in bodies:  # the atlas stores e.g. one "atrium" article under both atria
            lines.append({"key": text.name, "same_as": bodies[raw]})
            continue
        bodies[raw] = text.name
        url = TRAILING_URL.search(raw)
        body = raw[: url.start()].rstrip() if url else raw
        lines.append({"key": text.name, "source_url": url.group(0) if url else None, "text": body})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for line in lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    print(f"LUMEN articles: {len(lines)} ({len(bodies)} distinct) -> {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export one Z-Anatomy region for Lumen.")
    parser.add_argument("region", type=Path, help="region.json; the outputs are written next to it")
    parser.add_argument("--articles", type=Path, help="also write all description articles to this .jsonl file")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
    region = json.loads(args.region.read_text(encoding="utf-8"))
    out_dir = args.region.resolve().parent

    objects = collect(region)
    article_keys = {t.name for t in bpy.data.texts if t.as_string().strip() and not NOT_AN_ARTICLE.match(t.name)}
    ids = IdMaker()
    id_of: dict[str, str] = {}  # Z-Anatomy object name -> our id, for structures and groups

    # Structures: every real mesh or curve. Label lines, labels and groups are handled below.
    structure_objects, landmark_labels, skipped = [], [], []
    for obj in objects:
        base, suffix = split_name(obj.name)
        if suffix in GROUP or suffix in LABEL_LINE:
            continue
        if suffix in LANDMARK_LABEL:
            landmark_labels.append(obj)
        elif obj.type in ("MESH", "CURVE") and suffix in (None, "l", "r"):
            structure_objects.append(obj)
            id_of[obj.name] = ids.make(obj.name.replace(".", " "), obj.parent.name if obj.parent else "object")
        else:
            skipped.append(obj.name)

    # Groups: every ".g" object above something in the region, up to the top of the atlas.
    groups: dict[str, bpy.types.Object] = {}
    for obj in objects:
        ancestor = obj if split_name(obj.name)[1] in GROUP else obj.parent
        while ancestor:
            if split_name(ancestor.name)[1] in GROUP:
                groups[ancestor.name] = ancestor
            ancestor = ancestor.parent
    for name in sorted(groups):
        id_of[name] = ids.make(split_name(name)[0], "group")

    def parent_id(obj: bpy.types.Object) -> str | None:
        """The nearest ancestor that is a structure or a group in this export."""
        ancestor = obj.parent
        while ancestor and ancestor.name not in id_of:
            ancestor = ancestor.parent
        return id_of[ancestor.name] if ancestor else None

    def article(base: str) -> str | None:
        return base if base in article_keys else None

    # Shapes.
    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    export_collection = bpy.data.collections.new("Lumen region export")
    bpy.context.scene.collection.children.link(export_collection)
    structures, surfaces, pieces = [], {}, []
    for obj in structure_objects:
        structure_id = id_of[obj.name]
        base, suffix = split_name(obj.name)
        mesh = bake(obj, structure_id, depsgraph)
        baked = bpy.data.objects.new(structure_id, mesh)
        export_collection.objects.link(baked)
        baked.select_set(True)
        surfaces[structure_id] = BVHTree.FromPolygons([v.co.copy() for v in mesh.vertices], [tuple(p.vertices) for p in mesh.polygons])
        structures.append({
            "id": structure_id,
            "name": base,
            "side": SIDE.get(suffix),
            "kind": "tube" if obj.type == "CURVE" else "surface",
            "parent": parent_id(obj),
            "article": article(base),
            "z_anatomy_object": obj.name,
        })
        if obj.type == "CURVE":
            if obj.data.bevel_object or obj.data.bevel_mode != "ROUND":
                print(f"LUMEN warning: {obj.name} is not a plain round tube; its radius may be wrong")
            for index, spline in enumerate(obj.data.splines):
                path, radii = sample_spline(obj, spline)
                if len(path) < 2:
                    continue
                lengths = [0.0]
                for a, b in zip(path, path[1:]):
                    lengths.append(lengths[-1] + (b - a).length)
                pieces.append({
                    "id": f"{structure_id}.{index}", "structure": structure_id, "object": obj.name,
                    "parent_object": obj.parent.name if obj.parent else None, "system": top_ancestor(obj),
                    "path": path, "radii": radii, "lengths": lengths,
                })
    find_attachments(pieces)

    # Landmarks: a label and the line that points from it to a place on a structure.
    landmarks = []
    for label in landmark_labels:
        base, _ = split_name(label.name)
        line = next((c for c in label.children if split_name(c.name)[1] in LABEL_LINE and c.type == "MESH"), None)
        if line is None or len(line.data.vertices) != 2:
            skipped.append(label.name)
            continue
        ends = [line.matrix_world @ v.co for v in line.data.vertices]
        hits = []
        for end in ends:
            for structure_id, tree in surfaces.items():
                location, _normal, _index, distance = tree.find_nearest(end)
                if location is not None:
                    hits.append((distance, structure_id, end))
        distance, nearest, point = min(hits, key=lambda h: h[0]) if hits else (None, None, ends[-1])
        landmarks.append({
            "id": ids.make(base, "landmark"),
            "name": base,
            "parent": parent_id(label),
            "point": to_gltf(point),
            "nearest_structure": nearest,
            "distance_to_surface": round(distance, 5) if distance is not None else None,
            "article": article(base),
        })

    out_dir.mkdir(parents=True, exist_ok=True)
    glb_path = out_dir / "model.glb"
    bpy.ops.export_scene.gltf(
        filepath=str(glb_path),
        export_format="GLB",
        use_selection=True,
        export_apply=True,
        export_yup=True,
        export_texcoords=False,
        export_materials="NONE",
        export_animations=False,
        export_extras=False,
    )

    write_json(out_dir / "structures.json", {
        "region": region["id"],
        "name": region["name"],
        "source": "Z-Anatomy (Startup.blend), exported by backend/scripts/export_region.py. Do not edit by hand.",
        "units": "metres",
        "groups": [
            {"id": id_of[name], "name": split_name(name)[0], "parent": parent_id(obj), "article": article(split_name(name)[0])}
            for name, obj in sorted(groups.items())
        ],
        "structures": structures,
        "landmarks": landmarks,
    })

    by_structure: dict[str, list[dict]] = {}
    for piece in pieces:
        by_structure.setdefault(piece["structure"], []).append({
            "id": piece["id"],
            "length": round(piece["lengths"][-1], 5),
            "attach": piece["attach"],
            "radius": [round(r, 5) for r in piece["radii"]],
            "points": [to_gltf(p) for p in piece["path"]],
        })
    write_json(out_dir / "centerlines.json", {
        "region": region["id"],
        "source": "Z-Anatomy (Startup.blend), exported by backend/scripts/export_region.py. Do not edit by hand.",
        "units": "metres",
        "structures": by_structure,
    })

    if args.articles:
        export_articles(args.articles.resolve())

    print(f"LUMEN region {region['id']}: {len(structures)} structures ({len(by_structure)} tubes, {len(pieces)} pieces), "
          f"{len(groups)} groups, {len(landmarks)} landmarks, {glb_path.stat().st_size / 1_000_000:.1f} MB -> {out_dir}")
    if skipped:
        print(f"LUMEN skipped {len(skipped)} objects: {skipped}")


main()
