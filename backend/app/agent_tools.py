"""The tools the session agent can call, and the code that runs them.

Two kinds. Lookup tools ask about the model and the atlas' articles; they are
the plain functions in measure.py and articles.py, described here so Claude
knows when to call each. Hand-in tools are how the agent delivers its work: a
plan, one part, a decision, a summary. The agent module checks what is handed
in and sends back exactly what to fix.

Every distance is in metres along a centre-line piece.
"""

import json
from typing import Any

from app import measure, notes
from app.articles import Articles
from app.region import Region

READ_LIMIT = 8000  # characters of an article returned by read_article

_PIECE = {"type": "string", "description": 'A centre-line piece id, e.g. "anterior_interventricular_artery.0". Piece .0 is the trunk.'}
_STRETCH = {
    "type": "object",
    "description": "Part of one centre-line piece, in metres from its start.",
    "properties": {"piece": _PIECE, "from": {"type": "number"}, "to": {"type": "number"}},
    "required": ["piece", "from", "to"],
}
_IDS = {"type": "array", "items": {"type": "string"}}

# How much of a part's subject must show in its opening view, by kind of part.
MUST_SEE = {"click_case": 0.9, "damage_slider": 0.6, "pulse": 0.5, "demonstration": 0.3}
_SIDE = ["anterior", "posterior", "left", "right", "superior", "inferior"]

LOOKUP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "describe",
        "description": "What a structure or group is: what it sits inside, the article about it, and for a vessel the pieces of its centre line with their lengths. Call this before using a structure you have not looked at.",
        "input_schema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
    },
    {
        "name": "branches_of",
        "description": "Every branch that leaves one centre-line piece, in order, with the distance along the piece where it leaves and whether it is a named structure. Use it whenever a part depends on where a branch is, e.g. 'before the first septal branch'.",
        "input_schema": {"type": "object", "properties": {"piece": _PIECE}, "required": ["piece"]},
    },
    {
        "name": "beyond",
        "description": "Everything further from the trunk than a place: the rest of its piece and every branch leaving after it. In an artery this is what a blockage at that place cuts off.",
        "input_schema": {"type": "object", "properties": {"piece": _PIECE, "at": {"type": "number"}}, "required": ["piece", "at"]},
    },
    {
        "name": "route",
        "description": "The path from one place to another further from the trunk, and its length. Fails if the end is not beyond the start. Use it to check a pulse before handing it in.",
        "input_schema": {
            "type": "object",
            "properties": {"from_piece": _PIECE, "from_at": {"type": "number"}, "to_piece": _PIECE, "to_at": {"type": "number"}},
            "required": ["from_piece", "from_at", "to_piece", "to_at"],
        },
    },
    {
        "name": "find_view",
        "description": (
            "The side to look from, and what to hide, so the student sees enough of what a part is about when it opens. "
            "It tries every side and hides the cheapest things in front: veins, valve leaflets and the great vessels first, another artery next, "
            "a chamber only when nothing else works. It never hides the subject, and hides what `look_at` frames only when it must. "
            "You rarely need it: leave view.side out when you hand in a part and the same search fills in the side and adds to the hide list. "
            "Call it only when what you write depends on the view, such as 'seen from behind'. "
            "`kind` is the part's kind, which sets how much must show; the subject is `stretches` and/or `structures`; "
            "`hidden` is what the part hides already."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["demonstration", "pulse", "damage_slider", "click_case"]},
                "stretches": {"type": "array", "items": _STRETCH},
                "structures": _IDS,
                "look_at": _IDS,
                "hidden": _IDS,
            },
            "required": ["kind"],
        },
    },
    {
        "name": "search_notes",
        "description": "Search the student's notes for some words. Returns the best-matching passages, each with its page. Use it before the atlas whenever the student gave notes, and to find what the facts listed from the notes leave out. Quote from what it returns, or read the whole page with read_notes_page.",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    },
    {
        "name": "read_notes_page",
        "description": "The text of one page of the student's notes, counted from 1. Read it before quoting from it: a quote must be copied word for word.",
        "input_schema": {"type": "object", "properties": {"page": {"type": "integer"}}, "required": ["page"]},
    },
    {
        "name": "search_articles",
        "description": "Search the atlas' articles for some words. Returns the best-matching passages, each with the article it is from. Use the words a textbook would use. An article may be filed under another name than the model uses (the anterior interventricular artery is 'Left anterior descending artery').",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    },
    {
        "name": "read_article",
        "description": "The text of one article, by its key. Read it before quoting from it: a quote must be copied word for word.",
        "input_schema": {"type": "object", "properties": {"article": {"type": "string"}}, "required": ["article"]},
    },
]


def _stretches(items: list[dict] | None) -> list[measure.Stretch]:
    return [measure.Stretch(piece=item["piece"], start=item["from"], to=item["to"]) for item in items or []]


def _dump(result: Any) -> str:
    """A result as compact JSON, with stretches written the way a session writes them (`from`, not `start`)."""

    def rename(value: Any) -> Any:
        if isinstance(value, dict):
            return {("from" if key == "start" else key): rename(item) for key, item in value.items()}
        if isinstance(value, list):
            return [rename(item) for item in value]
        return round(value, 5) if isinstance(value, float) else value

    data = [item.model_dump() for item in result] if isinstance(result, list) else result.model_dump()
    return json.dumps(rename(data), separators=(",", ":"))


def run_lookup(name: str, args: dict[str, Any], region: Region, articles: Articles, pages: list[str] | None = None) -> str:
    """Run one lookup tool and return its result as text. Raises ValueError with a reason the agent can act on.

    `pages` is the text of each page of the student's notes, for the notes tools.
    """
    try:
        if name in ("search_notes", "read_notes_page") and not pages:
            return "The student gave no notes whose text could be read. Use the facts listed from the notes, if any, or the atlas."
        if name == "search_notes":
            found = notes.search(pages or [], args["query"])
            return _dump(found) if found else "Nothing in the notes matched. Try other words, or the words the notes might use."
        if name == "read_notes_page":
            return json.dumps({"page": args["page"], "text": notes.read_page(pages or [], int(args["page"]))})
        if name == "describe":
            return _dump(measure.describe(region, args["id"]))
        if name == "branches_of":
            return _dump(measure.branches_of(region, args["piece"]))
        if name == "beyond":
            return _dump(measure.beyond(region, args["piece"], args["at"]))
        if name == "route":
            return _dump(measure.route(region, args["from_piece"], args["from_at"], args["to_piece"], args["to_at"]))
        if name == "find_view":
            if args["kind"] not in MUST_SEE:
                raise ValueError(f"kind must be one of {sorted(MUST_SEE)}")
            choice = measure.choose_view(
                region,
                MUST_SEE[args["kind"]],
                stretches=_stretches(args.get("stretches")),
                structures=args.get("structures"),
                look_at=args.get("look_at"),
                hidden=args.get("hidden"),
            )
            # The best three sides are enough to choose from, and keep the reply short.
            return _dump(choice.model_copy(update={"sides": choice.sides[:3]}))
        if name == "search_articles":
            found = articles.search(args["query"], limit=5, prefer=region.article_keys)
            return _dump(found) if found else "No passage matched. Try other words."
        if name == "read_article":
            article = articles.get(args["article"])
            if article is None:
                raise ValueError(f"{args['article']!r} is not an article. Find its key with search_articles.")
            text = article.text
            if len(text) > READ_LIMIT:
                text = f"{text[:READ_LIMIT]}\n\n[The article continues for {len(article.text) - READ_LIMIT} more characters. Use search_articles to find passages further in.]"
            return json.dumps({"article": article.key, "text": text})
    except KeyError as missing:
        raise ValueError(f"{name} needs {missing.args[0]!r}") from None
    raise ValueError(f"There is no tool called {name!r}")


# Hand-in tools. The agent module checks what comes in; these schemas only tell Claude the shape.

_EVIDENCE = {
    "type": "object",
    "description": "Where the statement comes from. atlas: give `article` and `quote`. notes: give `fact`, or `page` and `quote`. model: for something measured with the tools, give nothing more.",
    "properties": {
        "type": {"type": "string", "enum": ["atlas", "notes", "model"]},
        "article": {"type": "string", "description": "atlas only: the article's key, as search_articles gives it"},
        "quote": {"type": "string", "description": "atlas, or notes with `page`: one or two sentences copied word for word from the article or the page that say what the statement says"},
        "fact": {"type": "integer", "description": "notes only: the number of a fact listed from the student's notes"},
        "page": {"type": "integer", "description": "notes only, in place of `fact`: the page of the notes the quote is on"},
    },
    "required": ["type"],
}
_STATEMENT = {
    "type": "object",
    "properties": {"text": {"type": "string", "description": "One or two plain sentences for the student."}, "source": _EVIDENCE},
    "required": ["text", "source"],
}
_STATEMENTS = {"type": "array", "items": _STATEMENT}
_PLACE = {"type": "object", "properties": {"piece": _PIECE, "at": {"type": "number"}}, "required": ["piece", "at"]}
_VIEW = {
    "type": "object",
    "description": "What the camera frames, and from which side of the body. Leave `side` out and the code chooses the side, and adds to `hide`, so the subject shows.",
    "properties": {"look_at": _IDS, "side": {"type": "string", "enum": _SIDE}},
    "required": ["look_at"],
}
_HIDE = {"type": "array", "items": {"type": "string"}, "description": "Structure or group ids hidden for this part, e.g. what is in front."}
_TARGET_PROPERTIES = {"regions": {"type": "array", "items": _STRETCH}, "structures": _IDS}
_COMMON = {"title": {"type": "string"}, "view": _VIEW, "hide": _HIDE}

SUBMIT_PART_TOOLS: dict[str, dict[str, Any]] = {
    "demonstration": {
        "name": "submit_demonstration",
        "description": "Hand in a demonstration: the model turns, hides what is in the way and tints some structures, with a line or two of explanation.",
        "input_schema": {
            "type": "object",
            "properties": {**_COMMON, "highlight": {**_IDS, "description": "Structures to tint."}, "statements": _STATEMENTS},
            "required": ["title", "view", "hide", "highlight", "statements"],
        },
    },
    "pulse": {
        "name": "submit_pulse",
        "description": "Hand in a travelling pulse: it runs along a vessel from `from` to `to`. With `to` null it spreads into every branch beyond `from`.",
        "input_schema": {
            "type": "object",
            "properties": {**_COMMON, "from": _PLACE, "to": {"anyOf": [_PLACE, {"type": "null"}]}, "statements": _STATEMENTS},
            "required": ["title", "view", "hide", "from", "to", "statements"],
        },
    },
    "damage_slider": {
        "name": "submit_damage_slider",
        "description": "Hand in a damage slider: the student drags a blockage along `track` and everything beyond it greys out. A zone's statement shows while the blockage is inside it.",
        "input_schema": {
            "type": "object",
            "properties": {
                **_COMMON,
                "track": _STRETCH,
                "start_at": {"type": "number", "description": "Where the blockage starts, in metres along the track's piece."},
                "zones": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"regions": {"type": "array", "items": _STRETCH}, "statement": _STATEMENT},
                        "required": ["regions", "statement"],
                    },
                },
                "statements": _STATEMENTS,
            },
            "required": ["title", "view", "hide", "track", "start_at", "zones", "statements"],
        },
    },
    "click_case": {
        "name": "submit_click_case",
        "description": "Hand in a click-where case: a short story about an invented patient, a question, the one place that is right, and feedback. Near misses are wrong places that deserve their own explanation; they may not overlap the answer.",
        "input_schema": {
            "type": "object",
            "properties": {
                **_COMMON,
                "story": {"type": "string"},
                "question": {"type": "string"},
                "answer": {"type": "object", "properties": _TARGET_PROPERTIES, "required": ["regions", "structures"]},
                "feedback": {
                    "type": "object",
                    "properties": {
                        "correct": _STATEMENT,
                        "wrong": _STATEMENT,
                        "near_misses": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {**_TARGET_PROPERTIES, "statement": _STATEMENT},
                                "required": ["regions", "structures", "statement"],
                            },
                        },
                    },
                    "required": ["correct", "wrong", "near_misses"],
                },
            },
            "required": ["title", "view", "hide", "story", "question", "answer", "feedback"],
        },
    },
}

_PART_KINDS = list(SUBMIT_PART_TOOLS)
_PLANNED_PART = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Shown to the student in the plan."},
        "kind": {"type": "string", "enum": _PART_KINDS},
        "intent": {"type": "string", "description": "A note to yourself: what this part should teach and on which structures. The student does not see it."},
    },
    "required": ["title", "kind", "intent"],
}

SUBMIT_PLAN_TOOL: dict[str, Any] = {
    "name": "submit_plan",
    "description": "Hand in the plan for the session.",
    "input_schema": {
        "type": "object",
        "properties": {
            "can_show": {"type": "array", "items": {"type": "string"}, "description": "Short sentences: what the model can show for this request."},
            "words_only": {"type": "array", "items": {"type": "string"}, "description": "Short sentences: what matters for this request but can only be explained, because the model lacks it."},
            "parts": {"type": "array", "items": _PLANNED_PART},
        },
        "required": ["can_show", "words_only", "parts"],
    },
}

ASK_STUDENT_TOOL: dict[str, Any] = {
    "name": "ask_student",
    "description": (
        "Ask the student one question instead of handing in a plan, when you can't tell what the session should cover. "
        "Nothing is built until they answer; their answer comes back in a new task."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "One short question, as you would say it to the student."},
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 4,
                "description": "Two to four short answers they can pick with one click, drawn from what this model can show. They can also type their own.",
            },
        },
        "required": ["question", "options"],
    },
}

ANSWER_STUDENT_TOOL: dict[str, Any] = {
    "name": "answer_student",
    "description": (
        "Answer what the student just said during the session. Every statement needs a source, as in a part. "
        "Change the plan only when they ask to go another way or what they said shows the plan no longer fits."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "statements": {**_STATEMENTS, "description": "One to four short statements: your answer."},
            "point_to": {**_IDS, "description": "Structure ids to select on the model so the student can see what you mean. May be empty."},
            "new_plan": {
                "type": "array",
                "items": _PLANNED_PART,
                "description": "Only to change direction: the parts that replace every part the student has not been given yet. Leave it out to keep the plan.",
            },
        },
        "required": ["statements", "point_to"],
    },
}

DECIDE_TOOL: dict[str, Any] = {
    "name": "decide_next",
    "description": "Say what should happen after the student's answers to a case: carry on with the plan, or put one extra part before the rest.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["continue", "insert"]},
            "reason": {"type": "string", "description": "What the wrong clicks suggest the student has not understood."},
            "part": {**_PLANNED_PART, "description": "insert only: the extra part."},
        },
        "required": ["action", "reason"],
    },
}

SUBMIT_SUMMARY_TOOL: dict[str, Any] = {
    "name": "submit_summary",
    "description": "Hand in the closing summary.",
    "input_schema": {
        "type": "object",
        "properties": {
            "solid": {"type": "array", "items": {"type": "string"}, "description": "Short phrases: what the student showed they understand, or was covered without trouble."},
            "shaky": {"type": "array", "items": {"type": "string"}, "description": "Short phrases: what to look at again, judged from their wrong clicks."},
        },
        "required": ["solid", "shaky"],
    },
}
