"""What the tutor is doing right now, in words a student can read while they wait.

Planning takes about 25 seconds and building a part 10 to 20, so the browser asks
GET /api/sessions/progress/{key} every second or so while it waits, and shows the
answer under its "thinking" line: "Building "Name the artery": reading the atlas
page on Ventricle (heart)".

Each piece of work the agent does (planning, one part, a chat answer, a decision)
is a stage. A stage has what is being done, the latest step within it, and how
long it has been going. Several stages can run at once, since parts are built
side by side. Nothing here is saved: it only matters while someone is waiting.
"""

import threading
import time
from typing import Any

from pydantic import BaseModel

from app.region import Region


class Working(BaseModel):
    """One piece of work under way."""

    stage: str  # as in the timings: "plan", "part <id>", "chat", "decide after <id>", "summary", "notes"
    doing: str  # for the student: "Building "Name the artery""
    detail: str | None  # the latest step: "Reading the atlas page on Ventricle (heart)"
    seconds: float  # since the stage began


class Progress:
    """The stages one session's agent has under way. Safe to use from the builder threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stages: dict[str, dict[str, Any]] = {}

    def begin(self, stage: str, doing: str) -> None:
        with self._lock:
            self._stages[stage] = {"doing": doing, "detail": None, "started": time.monotonic()}

    def step(self, stage: str, detail: str) -> None:
        with self._lock:
            if stage in self._stages:
                self._stages[stage]["detail"] = detail

    def end(self, stage: str) -> None:
        with self._lock:
            self._stages.pop(stage, None)

    def working(self) -> list[Working]:
        """Every stage under way, the one that began first first."""
        now = time.monotonic()
        with self._lock:
            stages = sorted(self._stages.items(), key=lambda item: item[1]["started"])
            return [Working(stage=stage, doing=s["doing"], detail=s["detail"], seconds=round(now - s["started"], 1)) for stage, s in stages]


def _the(name: str) -> str:
    """A structure's name as it reads mid-sentence: "the right coronary artery"."""
    return "the " + (name[0].lower() + name[1:] if name[1:2].islower() else name)


def page_title(url: str | None) -> str | None:
    """The title of the Wikipedia page a link goes to, as the browser shows an atlas source."""
    if not url or "wikipedia.org/wiki/" not in url:
        return None
    from urllib.parse import unquote

    return unquote(url.split("/wiki/", 1)[1].split("#", 1)[0].split("?", 1)[0]).replace("_", " ")


def describe_lookup(name: str, args: dict[str, Any], region: Region, articles: Any) -> str:
    """One lookup the agent makes, as a step the student can read."""
    try:
        if name == "describe":
            return f"Looking at {_the(region.name_of(args['id']))}"
        if name in ("branches_of", "beyond", "route"):
            piece = args.get("piece") or args.get("from_piece")
            vessel = _the(region.name_of(region.vessel_of(piece)))
            return {
                "branches_of": f"Finding the branches of {vessel}",
                "beyond": f"Working out what a blockage on {vessel} cuts off",
                "route": f"Tracing a route along {vessel}",
            }[name]
        if name == "find_view":
            return "Choosing a view"
        if name == "search_notes":
            return f"Searching your notes for “{args['query']}”"
        if name == "read_notes_page":
            return f"Reading page {args['page']} of your notes"
        if name == "search_articles":
            return f"Searching the atlas for “{args['query']}”"
        if name == "read_article":
            article = articles.get(args["article"])
            return f"Reading the atlas page on {page_title(article.url if article else None) or args['article']}"
    except (KeyError, TypeError, ValueError, AttributeError):
        pass
    return "Looking something up"
