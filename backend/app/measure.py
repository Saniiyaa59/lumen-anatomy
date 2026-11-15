"""Questions about the model that the session agent may not guess the answers to.

Each function reads the exported region and returns plain data: where the
branches of a vessel leave, what a blockage cuts off, whether a pulse can run
between two places, and what is in the way of seeing something. There is no AI
in here. The agent calls these as tools and builds its session from the answers.

Distances are metres along a centre-line piece, as in the session format.
"""

from typing import Literal

import numpy as np
from pydantic import BaseModel

from app.region import Region

Side = Literal["anterior", "posterior", "left", "right", "superior", "inferior"]

# Which way the camera looks from for each side: the same directions the viewer
# uses (frontend/src/viewer/controller.ts). The body faces +Z with the patient's
# left on +X; straight up and down are tilted a little, as in the viewer.
SIDE_DIRECTIONS: dict[Side, np.ndarray] = {
    "anterior": np.array([0.0, 0.0, 1.0]),
    "left": np.array([1.0, 0.0, 0.0]),
    "right": np.array([-1.0, 0.0, 0.0]),
    "posterior": np.array([0.0, 0.0, -1.0]),
    "superior": np.array([0.0, 1.0, 0.15]) / np.linalg.norm([0.0, 1.0, 0.15]),
    "inferior": np.array([0.0, -1.0, 0.15]) / np.linalg.norm([0.0, -1.0, 0.15]),
}
# How far back the viewer's camera stands when it frames something: it fits the
# sphere around it into a 45-degree view with this much room to spare.
CAMERA_HALF_ANGLE = np.radians(45 / 2)
FRAME_MARGIN = 1.35

JOIN_TOLERANCE = 0.001  # metres; a pulse may end this far before its start on the same piece
SAMPLE_SPACING = 0.003  # metres between the points tested along a stretch of vessel
SURFACE_SAMPLES = 60  # points tested on a structure that is not a vessel
SURFACE_SLACK = 0.001  # metres; how far in front of a point something must be to count as covering it


class _Out(BaseModel):
    """Results are models so they turn into JSON the same way everywhere."""


class Stretch(_Out):
    """Part of one centre-line piece. `start` is written `from` in a session."""

    piece: str
    start: float
    to: float


class PieceInfo(_Out):
    id: str
    length: float
    widest: float  # the largest tube radius along it
    joins: str | None  # the piece it branches off, if any
    joins_at: float | None  # how far along that piece


class Description(_Out):
    id: str
    name: str
    kind: Literal["group", "surface", "tube"]
    inside: list[str]  # names of the groups and structures it sits in, nearest first
    article: str | None  # its own article, or that of the nearest thing above it that has one
    article_is_own: bool
    members: list[str]  # for a group: ids of the structures in it; for a structure: ids of structures that are part of it
    pieces: list[PieceInfo]  # for a vessel: its centre line


class Branch(_Out):
    at: float  # how far along the piece this branch leaves
    piece: str
    structure: str
    name: str
    named: bool  # false when the branch is an unnamed piece of the same vessel
    length: float


class Beyond(_Out):
    stretches: list[Stretch]
    structures: list[str]  # every vessel that loses some part
    length: float  # total length cut off


class Route(_Out):
    segments: list[Stretch]  # in the order a pulse travels them
    length: float


class Blocker(_Out):
    structure: str
    name: str
    share: float  # share of the tested points this structure is in front of


class SideView(_Out):
    side: Side
    visible: float  # share of the tested points that can be seen now, from 0 to 1
    blockers: list[Blocker]  # what is in the way now, most blocking first
    hide_to_see_all: list[str]  # hiding these as well would show every tested point


class Visibility(_Out):
    points_tested: int
    sides: list[SideView]  # best first


def _require_piece(region: Region, piece_id: str) -> None:
    if piece_id not in region.pieces:
        raise ValueError(f"{piece_id!r} is not a centre-line piece in the {region.id} region")


def _require_place(region: Region, piece_id: str, at: float) -> None:
    _require_piece(region, piece_id)
    length = region.pieces[piece_id].length
    if not 0 <= at <= length + JOIN_TOLERANCE:
        raise ValueError(f"{at} is outside {piece_id!r}, which is {length} m long")


def describe(region: Region, entry_id: str) -> Description:
    """What a structure or group is: where it sits, its article, and for a vessel its centre line."""
    structure = region.structures.get(entry_id)
    group = region.groups.get(entry_id)
    entry = structure or group
    if entry is None:
        raise ValueError(f"{entry_id!r} is not a structure or a group in the {region.id} region")
    above = region.ancestors(entry_id)
    # A leaflet has no article of its own; its valve does.
    with_article = next((i for i in [entry_id, *above] if (region.structures.get(i) or region.groups[i]).article), None)
    article = (region.structures.get(with_article) or region.groups[with_article]).article if with_article else None
    pieces = [
        PieceInfo(
            id=piece.id,
            length=piece.length,
            widest=max(piece.radius),
            joins=piece.attach.piece if piece.attach else None,
            joins_at=piece.attach.at if piece.attach else None,
        )
        for piece in region.pieces_of.get(entry_id, [])
    ]
    members = region.structures_under(entry_id) if group else [s.id for s in region.structures.values() if s.parent == entry_id]
    return Description(
        id=entry_id,
        name=entry.name,
        kind=structure.kind if structure else "group",
        inside=[region.name_of(i) for i in above],
        article=article,
        article_is_own=with_article == entry_id,
        members=members,
        pieces=pieces,
    )


def branches_of(region: Region, piece_id: str) -> list[Branch]:
    """Every branch that leaves a piece, in order from its start."""
    _require_piece(region, piece_id)
    vessel = region.vessel_of(piece_id)
    return [
        Branch(
            at=branch.attach.at,
            piece=branch.id,
            structure=region.vessel_of(branch.id),
            name=region.name_of(region.vessel_of(branch.id)),
            named=region.vessel_of(branch.id) != vessel,
            length=branch.length,
        )
        for branch in region.branches.get(piece_id, [])
    ]


def beyond(region: Region, piece_id: str, at: float) -> Beyond:
    """Everything further from the trunk than a place: the rest of its piece and every branch that leaves after it.

    In an artery this is what a blockage there cuts off. In a vein blood flows
    toward the trunk, so this is what drains through that place, not what is lost.
    """
    _require_place(region, piece_id, at)
    stretches = [Stretch(piece=piece_id, start=min(at, region.pieces[piece_id].length), to=region.pieces[piece_id].length)]
    seen = {piece_id}

    def follow(host: str, after: float) -> None:
        for branch in region.branches.get(host, []):
            if branch.attach.at < after or branch.id in seen:
                continue
            seen.add(branch.id)
            stretches.append(Stretch(piece=branch.id, start=0.0, to=branch.length))
            follow(branch.id, 0.0)

    follow(piece_id, at)
    return Beyond(
        stretches=stretches,
        structures=list(dict.fromkeys(region.vessel_of(s.piece) for s in stretches)),
        length=sum(s.to - s.start for s in stretches),
    )


def route(region: Region, from_piece: str, from_at: float, to_piece: str, to_at: float) -> Route:
    """The path a pulse takes from one place to another further from the trunk. Fails if the end is not beyond the start."""
    _require_place(region, from_piece, from_at)
    _require_place(region, to_piece, to_at)
    # Walk back from the end toward the trunk until the starting piece is reached.
    chain: list[tuple[str, float]] = []
    piece_id = to_piece
    while piece_id != from_piece:
        attach = region.pieces[piece_id].attach
        if attach is None or len(chain) > len(region.pieces):
            raise ValueError(f"{to_piece!r} is not beyond {from_piece!r}, so a pulse can't run there")
        chain.insert(0, (piece_id, attach.at))
        piece_id = attach.piece
    segments: list[Stretch] = []
    current, start = from_piece, from_at
    for branch_id, leaves_at in chain:
        segments.append(Stretch(piece=current, start=start, to=leaves_at))
        current, start = branch_id, 0.0
    segments.append(Stretch(piece=current, start=start, to=to_at))
    if any(s.to < s.start - JOIN_TOLERANCE for s in segments):
        raise ValueError("the end is nearer the trunk than the start, so a pulse can't run there")
    return Route(segments=segments, length=sum(max(0.0, s.to - s.start) for s in segments))


def _camera(region: Region, look_at: list[str], direction: np.ndarray) -> np.ndarray:
    """Where the viewer's camera stands when it frames these structures from a direction."""
    low, high = region.shapes.bounds(look_at)
    radius = float(np.linalg.norm(high - low)) / 2
    return (low + high) / 2 + direction * (radius / np.sin(CAMERA_HALF_ANGLE) * FRAME_MARGIN)


def _test_points(region: Region, stretches: list[Stretch], structures: list[str]) -> list[tuple[np.ndarray, str, float]]:
    """Points to test for visibility: (point, the structure it is on, how much room that structure takes around it)."""
    points: list[tuple[np.ndarray, str, float]] = []
    for stretch in stretches:
        path = region.path(stretch.piece)
        count = max(3, int(np.ceil((stretch.to - stretch.start) / SAMPLE_SPACING)) + 1)
        for distance in np.linspace(stretch.start, stretch.to, count):
            # Anything nearer than the vessel's own wall is the vessel itself, not something in front.
            points.append((path.point_at(distance), region.vessel_of(stretch.piece), path.radius_at(distance) + SURFACE_SLACK))
    for structure_id in structures:
        vertices = np.asarray(region.shapes.meshes[structure_id].vertices)
        step = max(1, len(vertices) // SURFACE_SAMPLES)
        points += [(vertex, structure_id, SURFACE_SLACK) for vertex in vertices[::step]]
    return points


def what_hides(
    region: Region,
    stretches: list[Stretch] | None = None,
    structures: list[str] | None = None,
    look_at: list[str] | None = None,
    hidden: list[str] | None = None,
    sides: list[Side] | None = None,
) -> Visibility:
    """From each side of the body, how much of something can be seen and what is in the way.

    The thing to see is given as stretches of vessel and/or whole structures.
    `look_at` is what the part frames (its view), which decides where the camera
    stands; it defaults to the structures being looked for. `hidden` is what the
    part already hides (structure or group ids). Sight lines run from where the
    viewer's camera would stand to points on the target, so the answer matches
    the part's opening view, not every angle the student could turn to.
    """
    stretches = stretches or []
    structures = structures or []
    for stretch in stretches:
        _require_place(region, stretch.piece, stretch.start)
        _require_place(region, stretch.piece, stretch.to)
    unknown = [i for i in [*structures, *(look_at or [])] if i not in region.structures]
    if unknown:
        raise ValueError(f"not structures in the {region.id} region: {unknown}")
    points = _test_points(region, stretches, structures)
    if not points:
        raise ValueError("nothing to look for: give at least one stretch or one structure")
    framed = look_at or list(dict.fromkeys([*(region.vessel_of(s.piece) for s in stretches), *structures]))
    gone = set(region.expand(hidden or []))
    targets = np.array([point for point, _, _ in points])

    views: list[SideView] = []
    for side in sides or list(SIDE_DIRECTIONS):
        camera = _camera(region, framed, SIDE_DIRECTIONS[side])
        origins = np.repeat(camera[None, :], len(points), axis=0)
        reach = np.linalg.norm(targets - origins, axis=1)
        seen = 0
        in_front_now: dict[str, int] = {}
        in_front_ever: set[str] = set()
        for crossed, (_, own, room), distance in zip(region.shapes.crossed(origins, targets), points, reach):
            # A structure covers the point if the sight line meets it before reaching the point's own surface.
            covering = {i for i, met in crossed.items() if i != own and met < distance - room}
            in_front_ever |= covering
            showing = covering - gone
            seen += not showing
            for structure_id in showing:
                in_front_now[structure_id] = in_front_now.get(structure_id, 0) + 1
        views.append(
            SideView(
                side=side,
                visible=seen / len(points),
                blockers=[
                    Blocker(structure=i, name=region.name_of(i), share=count / len(points))
                    for i, count in sorted(in_front_now.items(), key=lambda item: (-item[1], item[0]))
                ],
                hide_to_see_all=sorted(in_front_ever - gone),
            )
        )
    # Best first: most visible now, then the side needing the least hidden.
    views.sort(key=lambda view: (-view.visible, len(view.hide_to_see_all)))
    return Visibility(points_tested=len(points), sides=views)
