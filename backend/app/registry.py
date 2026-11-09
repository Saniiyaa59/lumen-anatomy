"""Structure registry loaded from assets/structures.json.

The registry is the single source of truth for structure IDs. Reference
resolution, action validation, retrieval tags and paths all check IDs against
it, so a broken file is rejected at load time instead of failing later.
"""

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config import settings

Vector3 = tuple[float, float, float]


def normalize_name(name: str) -> str:
    """Lowercase, treat underscores and hyphens as spaces, drop a leading "the".

    "The Left_Ventricle" and "left ventricle" both become "left ventricle".
    """
    words = re.sub(r"[_\-\s]+", " ", name).strip().lower().split(" ")
    if len(words) > 1 and words[0] == "the":
        words = words[1:]
    return " ".join(words)


class Structure(BaseModel):
    """One clickable anatomical structure, made of one or more GLB meshes."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    display_name: str
    mesh_names: list[str] = Field(min_length=1)
    aliases: list[str] = []
    group: str
    layer: str
    size_class: Literal["small", "medium", "large"]
    best_view: str | None = None
    neighbors: list[str] = []
    short_description: str
    notes: str | None = None

    def names(self) -> list[str]:
        """Every name a student might use for this structure."""
        return [self.id, self.display_name, *self.aliases]


class View(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position: Vector3
    target: Vector3


class CrossSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    normal: Vector3
    default_position: float = Field(ge=0, le=1)


class FlowPath(BaseModel):
    # Extra fields allowed: the frontend adds animation control points here.
    model_config = ConfigDict(extra="allow")

    sequence: list[str] = Field(min_length=2)


class RegistryFile(BaseModel):
    """The whole structures.json file, with cross-reference checks."""

    model_config = ConfigDict(extra="forbid")

    organ: str
    structures: list[Structure] = Field(min_length=1)
    views: dict[str, View] = {}
    cross_sections: dict[str, CrossSection] = {}
    paths: dict[str, FlowPath] = {}

    @model_validator(mode="after")
    def check_references(self) -> "RegistryFile":
        ids = [s.id for s in self.structures]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate structure ids: {duplicates}")
        by_id = {s.id: s for s in self.structures}

        mesh_owner: dict[str, str] = {}
        name_owner: dict[str, str] = {}
        for s in self.structures:
            for mesh in s.mesh_names:
                if mesh in mesh_owner:
                    raise ValueError(f"mesh {mesh!r} is used by both {mesh_owner[mesh]!r} and {s.id!r}")
                mesh_owner[mesh] = s.id

            # Neighbor links must go both ways so retrieval expansion is symmetric.
            for n in s.neighbors:
                if n == s.id:
                    raise ValueError(f"{s.id!r} lists itself as a neighbor")
                if n not in by_id:
                    raise ValueError(f"{s.id!r} has unknown neighbor {n!r}")
                if s.id not in by_id[n].neighbors:
                    raise ValueError(f"{s.id!r} lists {n!r} as a neighbor, but not the other way round")

            if s.best_view is not None and s.best_view not in self.views:
                raise ValueError(f"{s.id!r} has unknown best_view {s.best_view!r}")

            # A name or alias must point to exactly one structure.
            for name in s.names():
                owner = name_owner.setdefault(normalize_name(name), s.id)
                if owner != s.id:
                    raise ValueError(f"name {name!r} matches both {owner!r} and {s.id!r}")

        for path_id, path in self.paths.items():
            unknown = [i for i in path.sequence if i not in by_id]
            if unknown:
                raise ValueError(f"path {path_id!r} has unknown structures: {unknown}")
        return self


class Registry:
    """Read-only lookups over a validated registry file."""

    def __init__(self, data: RegistryFile):
        self.organ = data.organ
        self.views = data.views
        self.cross_sections = data.cross_sections
        self.paths = data.paths
        self._by_id = {s.id: s for s in data.structures}
        self._by_mesh = {mesh: s.id for s in data.structures for mesh in s.mesh_names}
        self._by_name = {normalize_name(name): s.id for s in data.structures for name in s.names()}

    def __contains__(self, structure_id: str) -> bool:
        return structure_id in self._by_id

    def ids(self) -> list[str]:
        return list(self._by_id)

    def get(self, structure_id: str) -> Structure:
        """Return a structure by ID; raises KeyError for unknown IDs."""
        try:
            return self._by_id[structure_id]
        except KeyError:
            raise KeyError(f"unknown structure id {structure_id!r}") from None

    def find(self, name: str) -> Structure | None:
        """Exact match on ID, display name or alias, ignoring case and spacing."""
        structure_id = self._by_name.get(normalize_name(name))
        return self._by_id[structure_id] if structure_id else None

    def structure_for_mesh(self, mesh_name: str) -> str | None:
        return self._by_mesh.get(mesh_name)

    def list(self, group: str | None = None) -> list[Structure]:
        return [s for s in self._by_id.values() if group is None or s.group == group]


def load_registry(path: Path) -> Registry:
    return Registry(RegistryFile.model_validate_json(path.read_text(encoding="utf-8")))


@lru_cache
def get_registry() -> Registry:
    """The app-wide registry, loaded once from settings.registry_path."""
    return load_registry(settings.registry_path)
