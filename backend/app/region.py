"""A region of the atlas, loaded for the backend: its structures, centre lines and shapes.

The files come from backend/scripts/export_region.py and are the same ones the
viewer loads, so the backend and the browser cannot disagree about the model.
Everything is in metres, in the frame of model.glb (+Y up, the body facing +Z,
the patient's left on +X).

The shapes are loaded only when something asks a question about space (what
is in front of what), because that needs the geometry library and a moment to
build its search tree.
"""

import threading
from functools import cached_property, lru_cache
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from app.config import REPO_ROOT

REGIONS_DIR = REPO_ROOT / "assets" / "regions"

ID_PATTERN = r"^[a-z][a-z0-9_]*$"

Point = tuple[float, float, float]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Group(_Model):
    """A named group in the atlas, e.g. "Aortic valve". Groups have no shape of their own."""

    id: str = Field(pattern=ID_PATTERN)
    name: str
    parent: str | None
    article: str | None


class Structure(_Model):
    """One shape. Its mesh in model.glb has the same name as its id."""

    id: str = Field(pattern=ID_PATTERN)
    name: str
    side: Literal["left", "right"] | None
    kind: Literal["surface", "tube"]  # a tube is a vessel with a centre line
    parent: str | None
    article: str | None
    z_anatomy_object: str


class Landmark(_Model):
    id: str = Field(pattern=ID_PATTERN)
    name: str
    parent: str | None
    point: Point
    nearest_structure: str | None
    distance_to_surface: float | None
    article: str | None


class StructuresFile(_Model):
    region: str
    name: str
    source: str
    units: Literal["metres"]
    groups: list[Group]
    structures: list[Structure] = Field(min_length=1)
    landmarks: list[Landmark]


class Attach(_Model):
    """Where a piece branches off another: which piece, how far along it, and how far from its path."""

    piece: str
    at: float
    gap: float


class Piece(_Model):
    """One piece of a vessel's centre line: a trunk or a branch."""

    id: str
    length: float
    attach: Attach | None
    radius: list[float]
    points: list[Point]


class CenterlinesFile(_Model):
    region: str
    source: str
    units: Literal["metres"]
    structures: dict[str, list[Piece]]


class Path3:
    """A centre-line piece as arrays, for measuring along it."""

    def __init__(self, piece: Piece):
        self.points = np.asarray(piece.points, dtype=float)
        self.radius = np.asarray(piece.radius, dtype=float)
        steps = np.linalg.norm(np.diff(self.points, axis=0), axis=1)
        self.along = np.concatenate([[0.0], np.cumsum(steps)])
        self.length = float(self.along[-1])

    def point_at(self, distance: float) -> np.ndarray:
        """The point this far along the piece."""
        return np.array([np.interp(distance, self.along, self.points[:, axis]) for axis in range(3)])

    def radius_at(self, distance: float) -> float:
        return float(np.interp(distance, self.along, self.radius))


class Shapes:
    """Every mesh of a region as one, with a note of which structure each triangle belongs to."""

    def __init__(self, glb_path: Path, structure_ids: list[str]):
        # Imported here so that code which never asks about space doesn't pay for it.
        import trimesh

        scene = trimesh.load(glb_path, force="scene")
        missing = sorted(set(structure_ids) - set(scene.geometry))
        if missing:
            raise ValueError(f"{glb_path} has no mesh for: {missing}")
        self.ids = structure_ids
        self.meshes = {structure_id: scene.geometry[structure_id] for structure_id in structure_ids}
        self.whole = trimesh.util.concatenate([self.meshes[structure_id] for structure_id in structure_ids])
        # owner[i] is the index into `ids` of the structure that triangle i belongs to.
        self.owner = np.repeat(np.arange(len(structure_ids)), [len(self.meshes[i].faces) for i in structure_ids])
        # The search tree behind the ray casts must not be used by two threads at once: doing so
        # raises or crashes the process. Parts are built on background threads, so casts take turns.
        self._casting = threading.Lock()

    def bounds(self, structure_ids: list[str]) -> tuple[np.ndarray, np.ndarray]:
        """The box around these structures: its lowest and highest corner."""
        boxes = np.array([self.meshes[structure_id].bounds for structure_id in structure_ids])
        return boxes[:, 0].min(axis=0), boxes[:, 1].max(axis=0)

    def crossed(self, origins: np.ndarray, targets: np.ndarray) -> list[dict[str, float]]:
        """For each sight line from an origin to a target: the structures it crosses and how far along it first meets each."""
        directions = targets - origins
        distances = np.linalg.norm(directions, axis=1)
        directions = directions / distances[:, None]
        with self._casting:
            locations, ray, triangle = self.whole.ray.intersects_location(origins, directions, multiple_hits=True)
        met = np.linalg.norm(locations - origins[ray], axis=1)
        result: list[dict[str, float]] = [{} for _ in origins]
        for line, distance, face in zip(ray, met, triangle):
            structure_id = self.ids[self.owner[face]]
            if distance < result[line].get(structure_id, np.inf):
                result[line][structure_id] = float(distance)
        return result


class Region:
    """Read-only lookups over one exported region."""

    def __init__(self, folder: Path):
        self.folder = folder
        structures = StructuresFile.model_validate_json((folder / "structures.json").read_text(encoding="utf-8"))
        centerlines = CenterlinesFile.model_validate_json((folder / "centerlines.json").read_text(encoding="utf-8"))
        self.id = structures.region
        self.name = structures.name
        self.groups = {group.id: group for group in structures.groups}
        self.structures = {structure.id: structure for structure in structures.structures}
        self.landmarks = {landmark.id: landmark for landmark in structures.landmarks}
        self.pieces_of = centerlines.structures
        self.pieces = {piece.id: piece for pieces in centerlines.structures.values() for piece in pieces}
        self._vessel_of = {piece.id: structure_id for structure_id, pieces in centerlines.structures.items() for piece in pieces}
        self._paths: dict[str, Path3] = {}
        self._loading_shapes = threading.Lock()
        self._shapes: Shapes | None = None
        # Branches leaving each piece, nearest the start first.
        self.branches: dict[str, list[Piece]] = {}
        for piece in self.pieces.values():
            if piece.attach:
                self.branches.setdefault(piece.attach.piece, []).append(piece)
        for leaving in self.branches.values():
            leaving.sort(key=lambda piece: (piece.attach.at, piece.id))

    def vessel_of(self, piece_id: str) -> str:
        """The structure a centre-line piece belongs to."""
        return self._vessel_of[piece_id]

    def path(self, piece_id: str) -> Path3:
        if piece_id not in self._paths:
            self._paths[piece_id] = Path3(self.pieces[piece_id])
        return self._paths[piece_id]

    def parent_of(self, entry_id: str) -> str | None:
        entry = self.structures.get(entry_id) or self.groups.get(entry_id)
        return entry.parent if entry else None

    def ancestors(self, entry_id: str) -> list[str]:
        """Ids of everything a structure or group sits inside, nearest first."""
        chain: list[str] = []
        parent = self.parent_of(entry_id)
        while parent is not None and parent not in chain:
            chain.append(parent)
            parent = self.parent_of(parent)
        return chain

    def structures_under(self, group_id: str) -> list[str]:
        """Every structure inside a group, at any depth."""
        return [structure_id for structure_id in self.structures if group_id in self.ancestors(structure_id)]

    def expand(self, ids: list[str]) -> list[str]:
        """Turn a list of structure and group ids into the structures it covers, as a session's `hide` list means."""
        covered: list[str] = []
        for entry_id in ids:
            covered += [entry_id] if entry_id in self.structures else self.structures_under(entry_id)
        return list(dict.fromkeys(covered))

    def name_of(self, entry_id: str) -> str:
        entry = self.structures.get(entry_id) or self.groups.get(entry_id)
        return entry.name if entry else entry_id

    @cached_property
    def article_keys(self) -> frozenset[str]:
        """The articles the atlas links to something in this region."""
        entries = [*self.groups.values(), *self.structures.values(), *self.landmarks.values()]
        return frozenset(entry.article for entry in entries if entry.article)

    @property
    def shapes(self) -> Shapes:
        """The region's meshes, loaded the first time they are needed. Safe to ask for from several threads."""
        with self._loading_shapes:
            if self._shapes is None:
                self._shapes = Shapes(self.folder / "model.glb", list(self.structures))
            return self._shapes


@lru_cache
def get_region(region_id: str = "heart") -> Region:
    """A region by id, loaded once."""
    return Region(REGIONS_DIR / region_id)
