"""Check that assets/structures.json and assets/models/heart.glb agree.

Reports registry mesh names that are missing from the GLB (a typo, or a mesh
dropped from the export) and GLB meshes no structure claims (unclickable in
the viewer). Exits with status 1 if either list is non-empty.

Run from backend/ with the venv active:

    python -m scripts.validate_glb
    python -m scripts.validate_glb --glb path/to/other.glb --registry path/to/structures.json
"""

import argparse
import json
import struct
import sys
from pathlib import Path

from pydantic import ValidationError

from app.config import REPO_ROOT, settings
from app.registry import Registry, load_registry

DEFAULT_GLB = REPO_ROOT / "assets" / "models" / "heart.glb"

GLB_MAGIC = b"glTF"
JSON_CHUNK = b"JSON"


def read_glb_mesh_names(path: Path) -> set[str]:
    """Return the names of the nodes that carry a mesh.

    A GLB file is a 12-byte header, then a JSON chunk describing the scene,
    then a binary chunk with the geometry. Only the JSON chunk is needed.
    Node names are used rather than mesh names because Three.js names each
    loaded object after its node.
    """
    with path.open("rb") as f:
        magic, version, _length = struct.unpack("<4sII", f.read(12))
        if magic != GLB_MAGIC:
            raise ValueError(f"{path} is not a GLB file")
        if version != 2:
            raise ValueError(f"{path} is glTF version {version}; expected 2")
        chunk_length, chunk_type = struct.unpack("<I4s", f.read(8))
        if chunk_type != JSON_CHUNK:
            raise ValueError(f"{path} does not start with a JSON chunk")
        gltf = json.loads(f.read(chunk_length))
    return {node["name"] for node in gltf.get("nodes", []) if "mesh" in node and "name" in node}


def compare(glb_names: set[str], registry: Registry) -> tuple[list[str], list[str]]:
    """Return (registry meshes missing from the GLB, GLB meshes no structure uses)."""
    registry_names = {mesh for s in registry.list() for mesh in s.mesh_names}
    return sorted(registry_names - glb_names), sorted(glb_names - registry_names)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--glb", type=Path, default=DEFAULT_GLB)
    parser.add_argument("--registry", type=Path, default=settings.registry_path)
    args = parser.parse_args(argv)

    try:
        registry = load_registry(args.registry)
    except ValidationError as error:
        print(f"{args.registry} is invalid:\n{error}")
        return 1
    glb_names = read_glb_mesh_names(args.glb)
    missing, unused = compare(glb_names, registry)

    print(f"{len(registry.ids())} structures, {len(glb_names)} meshes in {args.glb.name}")
    for mesh in missing:
        print(f"  missing from GLB: {mesh} ({registry.structure_for_mesh(mesh)})")
    for mesh in unused:
        print(f"  not in registry:  {mesh}")
    if missing or unused:
        return 1
    print("OK: every mesh belongs to exactly one structure.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
