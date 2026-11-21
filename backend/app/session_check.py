"""Check that a session refers only to things that exist on the model.

The models in session_schemas.py check a session's shape. This checks its
references: every structure, group and centre-line piece is real, every
distance lies on its piece, a pulse's end is beyond its start, and every atlas
source names a real article with the right link. The browser makes the same
checks on the model (frontend/src/session/format.ts); this lets the backend
find a bad part before it is sent, and lets the agent be told exactly what to fix.

Each problem is a sentence starting with the path to the field, as on the frontend.
"""

from app import measure
from app.articles import Articles
from app.region import Region
from app.session_schemas import (
    ClickCase,
    DamageSlider,
    Demonstration,
    MultipleChoice,
    Part,
    Place,
    Pulse,
    RecordedSession,
    Source,
    Statement,
)
from app.session_schemas import Region as Stretch

EPSILON = 1e-4  # metres of slack for rounding in the files


class _Check:
    def __init__(self, region: Region, articles: Articles | None):
        self.region = region
        self.articles = articles
        self.problems: list[str] = []

    def fail(self, path: str, message: str) -> None:
        self.problems.append(f"{path}: {message}")

    def structures(self, ids: list[str], path: str) -> None:
        for index, structure_id in enumerate(ids):
            if structure_id not in self.region.structures:
                self.fail(f"{path}[{index}]", f'"{structure_id}" is not a structure in this region')

    def structures_or_groups(self, ids: list[str], path: str) -> None:
        for index, entry_id in enumerate(ids):
            if entry_id not in self.region.structures and entry_id not in self.region.groups:
                self.fail(f"{path}[{index}]", f'"{entry_id}" is not a structure or a group in this region')

    def place(self, place: Place, path: str) -> bool:
        piece = self.region.pieces.get(place.piece)
        if piece is None:
            self.fail(f"{path}.piece", f'"{place.piece}" is not a centre-line piece in this region')
            return False
        if place.at > piece.length + EPSILON:
            self.fail(f"{path}.at", f"{place.at} is outside the piece, which is {piece.length} m long")
            return False
        return True

    def stretch(self, stretch: Stretch, path: str) -> None:
        piece = self.region.pieces.get(stretch.piece)
        if piece is None:
            self.fail(f"{path}.piece", f'"{stretch.piece}" is not a centre-line piece in this region')
        elif stretch.to > piece.length + EPSILON:
            self.fail(path, f"from {stretch.start} to {stretch.to} is not a stretch of the piece, which is {piece.length} m long")

    def stretches(self, stretches: list[Stretch], path: str) -> None:
        for index, stretch in enumerate(stretches):
            self.stretch(stretch, f"{path}[{index}]")

    def source(self, source: Source, path: str) -> None:
        if source.type != "atlas" or self.articles is None:
            return
        article = self.articles.get(source.article)
        if article is None:
            self.fail(f"{path}.article", f'"{source.article}" is not an article in the atlas')
        elif source.url != article.url:
            self.fail(f"{path}.url", f"must be the article's own link, {article.url}")

    def statement(self, statement: Statement, path: str) -> None:
        self.source(statement.source, f"{path}.source")

    def part(self, part: Part, path: str) -> None:
        self.structures(part.view.look_at, f"{path}.view.look_at")
        self.structures_or_groups(part.hide, f"{path}.hide")
        for index, statement in enumerate(part.statements):
            self.statement(statement, f"{path}.statements[{index}]")

        if isinstance(part, Demonstration):
            self.structures(part.highlight, f"{path}.highlight")
        elif isinstance(part, Pulse):
            starts = self.place(part.start, f"{path}.from")
            ends = part.to is None or self.place(part.to, f"{path}.to")
            if starts and ends and part.to is not None:
                try:
                    measure.route(self.region, part.start.piece, part.start.at, part.to.piece, part.to.at)
                except ValueError:
                    self.fail(f"{path}.to", "is not further along the vessel than the start, so a pulse can't run there")
        elif isinstance(part, DamageSlider):
            self.stretch(part.track, f"{path}.track")
            for index, zone in enumerate(part.zones):
                self.stretches(zone.regions, f"{path}.zones[{index}].regions")
                self.statement(zone.statement, f"{path}.zones[{index}].statement")
        elif isinstance(part, ClickCase):
            self.stretches(part.answer.regions, f"{path}.answer.regions")
            self.structures(part.answer.structures, f"{path}.answer.structures")
            self.statement(part.feedback.correct, f"{path}.feedback.correct")
            self.statement(part.feedback.wrong, f"{path}.feedback.wrong")
            for index, miss in enumerate(part.feedback.near_misses):
                miss_path = f"{path}.feedback.near_misses[{index}]"
                self.stretches(miss.regions, f"{miss_path}.regions")
                self.structures(miss.structures, f"{miss_path}.structures")
                self.statement(miss.statement, f"{miss_path}.statement")
        elif isinstance(part, MultipleChoice):
            self.structures(part.highlight, f"{path}.highlight")
            for index, option in enumerate(part.options):
                self.statement(option.feedback, f"{path}.options[{index}].feedback")


def check_part(part: Part, region: Region, articles: Articles | None = None) -> list[str]:
    """Everything in one part that does not exist on the model, or an empty list.

    With `articles` given, atlas sources are checked too: the browser cannot do
    that, because the articles are too large to load there.
    """
    check = _Check(region, articles)
    check.part(part, "part")
    return check.problems


def check_session(session: RecordedSession, region: Region, articles: Articles | None = None) -> list[str]:
    """Everything in a whole session that does not exist on the model, or an empty list."""
    check = _Check(region, articles)
    if session.region != region.id:
        check.fail("session.region", f'must be "{region.id}", the region being checked against')
    for index, part in enumerate(session.parts):
        check.part(part, f"session.parts[{index}]")
    for index, source in enumerate(session.summary.sources):
        check.source(source, f"session.summary.sources[{index}]")
    return check.problems
