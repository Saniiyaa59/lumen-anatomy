"""The session agent: Claude building a study session, held to what can be checked.

Claude decides what to teach, which structures to use, what to look up and how
to put it. Plain code decides whether the result is allowed:

  - every distance and branch comes from a lookup tool, never from memory;
  - every part must fit the session format and refer only to real things;
  - every statement needs evidence: a word-for-word quote from an atlas
    article, a fact read from the student's notes, or a measurement;
  - what a part is about must be visible in the view it opens with.

When a part fails a check, Claude is told exactly which field and why, and
tries again. After a few failures the part is given up on.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, TypeAdapter, ValidationError

from app import measure
from app.agent_tools import DECIDE_TOOL, LOOKUP_TOOLS, SUBMIT_PART_TOOLS, SUBMIT_PLAN_TOOL, SUBMIT_SUMMARY_TOOL, run_lookup
from app.articles import Articles
from app.llm import LLM, Usage
from app.region import Region
from app.session_check import check_part
from app.session_schemas import ClickAnswer, ClickCase, DamageSlider, Demonstration, Part, PartKind, Pulse, Scope, Source

MAX_TURNS = 24  # requests to Claude for one piece of work, lookups included
MAX_HAND_INS = 4  # times one part may be handed in before it is given up on
MAX_NOTE_FACTS = 40
MIN_QUOTE_CHARS = 20
CLICK_TOLERANCE = 0.002  # metres past the end of an answer region that still count

# How much of a part's subject must be visible in its opening view.
MUST_SEE = {"click_case": 0.9, "damage_slider": 0.6, "pulse": 0.5, "demonstration": 0.3}

PART_ADAPTER: TypeAdapter[Part] = TypeAdapter(Part)

SYSTEM = """You are the tutor inside Lumen, a study tool built on a 3D anatomy model. A student says what they need to be ready for. You build a short study session that plays on the model of the {region_name}, one part at a time.

# The four kinds of part

- demonstration: the camera frames some structures, hides what is in the way and tints the ones being discussed, beside a line or two of explanation.
- pulse: a pulse runs along a vessel from one place to another, or spreads into every branch beyond a place, to show a course and its branching.
- damage_slider: the student drags a blockage along one piece of a vessel; everything beyond it greys out. Text can change as the blockage enters different zones.
- click_case: a short story about an invented patient, then "click where the problem is". The student answers by clicking the model and is graded by the exact place.

Sessions are built around reasoning, not naming: what follows if this is blocked here, and where must the problem be given these findings.

# The model

Structures are listed below as `id | name | kind | inside`. A group has no shape; it only gathers structures. A tube is a vessel with a centre line made of pieces named `<structure id>.<n>`; piece `.0` is the trunk and the others are branches. A place on a vessel is a piece and a distance along it in metres.

{structure_list}

What this model cannot show: which part of an organ's wall a vessel supplies (there are no territories), anything that moves, and anything not in the list above. Some branches are drawn but have no name of their own; `branches_of` marks them as unnamed. Say so plainly when a request depends on something the model lacks.

# Rules that are checked

1. Never state a distance, the order of branches, or what lies beyond a point from memory. Ask the tools. All distances are metres.
2. Every statement the student reads needs a source:
   - atlas: the article's key and a quote copied word for word from it that says what your statement says. Search, then read the article, then quote.
   - notes: the number of a fact from the student's notes, when notes were given. Prefer the notes. If the notes and the atlas disagree, follow the notes and say that they differ.
   - model: only for what you measured with the tools, such as a length or where a branch leaves.
3. The student must be able to see what a part is about when it opens. Use `what_hides` to choose the side to look from and what to hide. For a click case the whole answer must be visible. Hide as little as will do: try another side before hiding a chamber that a vessel lies on, because a vessel floating in space teaches less. Hiding veins, valve leaflets and the great vessels in front is fine.
4. A click case needs exactly one right place. Give findings that only that place explains, and check with `beyond` that they match what the model shows. Add near misses for the wrong clicks a student is likely to make, each with its own short explanation. A near miss may not overlap the answer.

# Writing

Write for a student who is revising: short, plain sentences, one idea each. One to three statements in a part. A patient story is three sentences at most and uses findings, not the name of the answer. Titles are a few words.

The tools and the hand-in fields work in metres. The student does not: in anything they read, give a length in millimetres, rounded to a whole number ("about 46 mm"), and never show a piece id such as `left_coronary_artery.0`. Use a measurement only where it helps; most statements need none.

In the plan, `can_show` and `words_only` are for the student too: at most four short sentences each, with no measurements and no ids.

You finish each piece of work by calling the hand-in tool you are given. If it is not accepted, it says which field is wrong and why: fix that and hand it in again."""


class AgentError(Exception):
    """The agent could not produce something usable."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


class _Rejected(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass
class NoteFact:
    """Something the student's notes say, with the page it is on. Read by Claude; the page and quote come from the API."""

    number: int
    text: str
    file: str
    page: int
    quote: str


@dataclass
class PlannedPart:
    part_id: str
    title: str
    kind: PartKind
    intent: str  # the agent's own note of what the part should teach


@dataclass
class Brief:
    """What every stage of one session needs to know."""

    request: str
    facts: list[NoteFact] = field(default_factory=list)
    scope: Scope | None = None
    plan: list[PlannedPart] = field(default_factory=list)
    built: list[Part] = field(default_factory=list)  # parts already handed to the student, in order


def _squash(text: str) -> str:
    """Text with case and spacing ironed out, for comparing a quote with its article."""
    return re.sub(r"\s+", " ", text).strip().lower()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:32] or "part"


class Agent:
    def __init__(self, llm: LLM, region: Region, articles: Articles, usage: Usage | None = None):
        self.llm = llm
        self.region = region
        self.articles = articles
        self.usage = usage or Usage()
        listing = [f"{group.id} | {group.name} | group | {group.parent or '-'}" for group in region.groups.values()]
        listing += [f"{s.id} | {s.name} | {s.kind} | {s.parent or '-'}" for s in region.structures.values()]
        self.system = SYSTEM.format(region_name=region.name.lower(), structure_list="\n".join(listing))

    # Talking to Claude

    def _ask(self, messages: list[dict], tools: list[dict] | None = None) -> Any:
        response = self.llm.ask(system=self.system, messages=messages, tools=tools)
        self.usage.add(getattr(response, "usage", None))
        return response

    def _work(self, task: str, hand_in: dict[str, Any], accept: Callable[[dict], Any]) -> Any:
        """Let Claude work on a task with the lookup tools until what it hands in is accepted."""
        tools = [*LOOKUP_TOOLS, hand_in]
        messages: list[dict] = [{"role": "user", "content": task}]
        problems = ["nothing was handed in"]
        hand_ins = 0
        for _ in range(MAX_TURNS):
            response = self._ask(messages, tools)
            messages.append({"role": "assistant", "content": response.content})
            calls = [block for block in response.content if block.type == "tool_use"]
            if not calls:
                messages.append({"role": "user", "content": f"Finish by calling {hand_in['name']}."})
                continue
            results = []
            for call in calls:
                failed = False
                if call.name == hand_in["name"]:
                    hand_ins += 1
                    try:
                        return accept(call.input)
                    except _Rejected as rejected:
                        problems = rejected.problems
                        content = "Not accepted. Fix these and hand it in again:\n- " + "\n- ".join(problems)
                        failed = True
                else:
                    try:
                        content = run_lookup(call.name, call.input, self.region, self.articles)
                    except (ValueError, TypeError) as error:
                        content, failed = str(error), True
                results.append({"type": "tool_result", "tool_use_id": call.id, "content": content, **({"is_error": True} if failed else {})})
            if hand_ins >= MAX_HAND_INS:
                raise AgentError(problems)
            # Every result of a turn goes back in one message.
            messages.append({"role": "user", "content": results})
        raise AgentError(["ran out of turns", *problems])

    def _background(self, brief: Brief) -> str:
        """What the session is for and what has happened so far, as text for a task."""
        lines = [f"The student asked: {brief.request}", ""]
        if brief.facts:
            lines.append("Facts from the student's notes (cite one as source type notes with its number):")
            lines += [f"{fact.number}. {fact.text} (page {fact.page})" for fact in brief.facts]
        else:
            lines.append("The student gave no notes that could be read. Use the atlas.")
        if brief.plan:
            lines += ["", "The plan:"]
            lines += [f"- [{item.kind}] {item.title}: {item.intent}" for item in brief.plan]
        if brief.built:
            lines += ["", "Parts the student has already been given (do not repeat what they said):"]
            for part in brief.built:
                said = " ".join(statement.text for statement in part.statements)
                lines.append(f"- [{part.kind}] {part.title}: {said}" if said else f"- [{part.kind}] {part.title}")
        return "\n".join(lines)

    # Reading the notes

    def read_notes(self, request: str, pdf_base64: str, filename: str) -> list[NoteFact]:
        """Have Claude pull the relevant facts out of the notes. The API attaches the page and the exact text each fact rests on."""
        response = self._ask(
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_base64},
                            "title": filename,
                            "citations": {"enabled": True},
                        },
                        {
                            "type": "text",
                            "text": f"These are a student's lecture notes. They asked: {request}\n\nList what the notes say that matters for this, one fact per sentence, each on its own line. Use only what is written in the notes. If the notes say nothing relevant, reply with the single word NONE.",
                        },
                    ],
                }
            ]
        )
        facts: list[NoteFact] = []
        for block in response.content:
            cited = [c for c in (getattr(block, "citations", None) or []) if getattr(c, "type", "") == "page_location"]
            text = (getattr(block, "text", "") or "").strip()
            if block.type != "text" or not cited or not text:
                continue
            facts.append(NoteFact(number=len(facts) + 1, text=text, file=filename, page=cited[0].start_page_number, quote=cited[0].cited_text))
            if len(facts) >= MAX_NOTE_FACTS:
                break
        return facts

    # Scope and plan

    def plan(self, brief: Brief) -> None:
        """Work out what the model can show for this request and plan the parts. Fills `brief.scope` and `brief.plan`."""
        task = (
            f"{self._background(brief)}\n\n"
            "Work out what the model can show for this and what it can only explain, then plan the session: three or four parts that build on each other and end with a click_case. "
            "Look at the structures you intend to use with `describe` and `branches_of` first, so the plan fits what the model has. "
            "Hand the plan in with submit_plan."
        )

        def accept(raw: dict) -> None:
            problems = []
            parts = raw.get("parts")
            if not isinstance(parts, list) or not 2 <= len(parts) <= 5:
                raise _Rejected(["parts: plan between two and five parts"])
            planned: list[PlannedPart] = []
            for index, item in enumerate(parts):
                kind = item.get("kind") if isinstance(item, dict) else None
                title = str(item.get("title", "")).strip() if isinstance(item, dict) else ""
                if kind not in SUBMIT_PART_TOOLS:
                    problems.append(f"parts[{index}].kind: must be one of {', '.join(SUBMIT_PART_TOOLS)}")
                elif not title:
                    problems.append(f"parts[{index}].title: must not be empty")
                else:
                    planned.append(PlannedPart(f"p{index + 1}-{_slug(title)}", title, kind, str(item.get("intent", "")).strip()))
            if not any(item.kind == "click_case" for item in planned):
                problems.append("parts: include at least one click_case")
            try:
                scope = Scope(can_show=raw.get("can_show") or [], words_only=raw.get("words_only") or [])
            except ValidationError:
                problems.append("can_show and words_only: must be lists of non-empty sentences")
            if problems:
                raise _Rejected(problems)
            brief.scope, brief.plan = scope, planned

        self._work(task, SUBMIT_PLAN_TOOL, accept)

    # Building a part

    def build(self, brief: Brief, item: PlannedPart) -> Part:
        """Build one planned part, checked. Raises AgentError if nothing acceptable came after several tries."""
        task = (
            f"{self._background(brief)}\n\n"
            f'Build this part now: [{item.kind}] "{item.title}". What it should teach: {item.intent}\n\n'
            f"Look up what you need, choose the view with `what_hides`, then hand it in with {SUBMIT_PART_TOOLS[item.kind]['name']}."
        )
        return self._work(task, SUBMIT_PART_TOOLS[item.kind], lambda raw: self._accept_part(brief, item, raw))

    def _source(self, brief: Brief, evidence: Any, path: str, problems: list[str]) -> dict | None:
        """Turn the agent's evidence for a statement into a session source, or record why it is not good enough."""
        kind = evidence.get("type") if isinstance(evidence, dict) else None
        if kind == "model":
            return {"type": "model"}
        if kind == "notes":
            fact = next((f for f in brief.facts if f.number == evidence.get("fact")), None)
            if fact is None:
                problems.append(f"{path}.fact: there is no notes fact with that number")
                return None
            return {"type": "notes", "file": fact.file, "page": fact.page}
        if kind == "atlas":
            article = self.articles.get(str(evidence.get("article", "")))
            quote = str(evidence.get("quote", ""))
            if article is None:
                problems.append(f'{path}.article: "{evidence.get("article")}" is not an article; find its key with search_articles')
            elif len(quote.strip()) < MIN_QUOTE_CHARS:
                problems.append(f"{path}.quote: give a full sentence copied from the article")
            elif _squash(quote) not in _squash(article.text):
                problems.append(f'{path}.quote: this is not in "{article.key}" word for word; read the article and copy the sentence exactly')
            else:
                return {"type": "atlas", "article": evidence["article"], "url": article.url}
            return None
        problems.append(f"{path}.type: must be atlas, notes or model")
        return None

    def _with_sources(self, brief: Brief, value: Any, path: str, problems: list[str]) -> Any:
        """A copy of what was handed in, with every statement's evidence replaced by a checked source."""
        if isinstance(value, list):
            return [self._with_sources(brief, item, f"{path}[{index}]", problems) for index, item in enumerate(value)]
        if not isinstance(value, dict):
            return value
        if "text" in value and "source" in value:
            source = self._source(brief, value["source"], f"{path}.source", problems)
            return {"text": value["text"], "source": source or {"type": "model"}}
        return {key: self._with_sources(brief, item, f"{path}.{key}", problems) for key, item in value.items()}

    def _accept_part(self, brief: Brief, item: PlannedPart, raw: dict) -> Part:
        problems: list[str] = []
        draft = self._with_sources(brief, raw, "part", problems)
        # The title is the one the student already saw in the plan, whatever the agent calls the part now.
        draft.update(id=item.part_id, kind=item.kind, title=item.title)
        draft.setdefault("statements", [])  # a case tells its story in its own fields
        if item.kind == "click_case" and isinstance(draft.get("answer"), dict):
            draft["answer"]["tolerance"] = CLICK_TOLERANCE
        try:
            part = PART_ADAPTER.validate_python(draft)
        except ValidationError as error:
            # The first step of each location is the kind of part, which the agent already knows.
            shape = [f"{'.'.join(['part', *(str(step) for step in e['loc'][1:])])}: {e['msg']}" for e in error.errors()]
            raise _Rejected([*problems, *shape]) from None
        problems += check_part(part, self.region, self.articles)
        if not problems:
            problems += self._seeing_problems(part)
        if problems:
            raise _Rejected(problems)
        return part

    def _seeing_problems(self, part: Part) -> list[str]:
        """Why the student could not see what this part is about when it opens, if they couldn't."""
        stretches: list[measure.Stretch] = []
        structures: list[str] = []
        if isinstance(part, ClickCase):
            stretches = [measure.Stretch(piece=r.piece, start=r.start, to=r.to) for r in part.answer.regions]
            structures = list(part.answer.structures)
            what = "the answer"
        elif isinstance(part, DamageSlider):
            stretches = [measure.Stretch(piece=part.track.piece, start=part.track.start, to=part.track.to)]
            what = "the slider's track"
        elif isinstance(part, Pulse):
            if part.to is not None:
                stretches = measure.route(self.region, part.start.piece, part.start.at, part.to.piece, part.to.at).segments
            else:
                stretches = measure.beyond(self.region, part.start.piece, part.start.at).stretches
            stretches = [s for s in stretches if s.to > s.start]
            what = "the pulse's route"
        elif isinstance(part, Demonstration):
            structures = list(part.highlight)
            what = "the highlighted structures"
        if not stretches and not structures:
            return []
        if part.view.side is None:
            return ["part.view.side: choose a side, so that what the part is about is known to be visible"]
        seen = measure.what_hides(
            self.region, stretches=stretches, structures=structures, look_at=part.view.look_at, hidden=part.hide, sides=[part.view.side]
        ).sides[0]
        if seen.visible >= MUST_SEE[part.kind]:
            return []
        blockers = ", ".join(f"{b.structure} ({b.share:.0%})" for b in seen.blockers[:4])
        return [
            f"part.view: only {seen.visible:.0%} of {what} can be seen from the {part.view.side} with this hide list. "
            f"In front of it: {blockers}. Hide what is in front, or use what_hides to find a better side."
        ]

    # Replanning

    def decide(self, brief: Brief, case: ClickCase, answers: list[ClickAnswer]) -> PlannedPart | None:
        """After a case the student got wrong at least once: carry on, or put one extra part first. Returns the extra part, if any."""
        clicks = []
        for answer in answers:
            where = f"{answer.piece} at {answer.at:.4f} m" if answer.piece is not None and answer.at is not None else "not on a vessel"
            clicks.append(f"- try {answer.attempt}: {self.region.name_of(answer.structure_id)} ({where}); {'correct' if answer.correct else 'wrong'}")
        regions = ", ".join(f"{r.piece} from {r.start} to {r.to}" for r in case.answer.regions) or "none"
        remaining = [item for item in brief.plan if item.part_id not in {part.id for part in brief.built}]
        task = (
            f"{self._background(brief)}\n\n"
            f'The student has just finished the case "{case.title}".\n'
            f"Story: {case.story}\nQuestion: {case.question}\n"
            f"Right answer: regions {regions}; structures {', '.join(case.answer.structures) or 'none'}.\n"
            "Their clicks:\n" + "\n".join(clicks) + "\n\n"
            "Still to come: " + (", ".join(f"[{item.kind}] {item.title}" for item in remaining) or "nothing; the summary is next") + "\n\n"
            "Decide what the wrong clicks say about what they have not understood. If one extra part before the rest would fix it, such as a demonstration of the point they missed or an easier case, ask for it. "
            "If what is still to come already covers it, or the slip was small, carry on. Answer with decide_next."
        )

        def accept(raw: dict) -> PlannedPart | None:
            if raw.get("action") == "continue":
                return None
            extra = raw.get("part") if isinstance(raw.get("part"), dict) else {}
            if raw.get("action") != "insert" or extra.get("kind") not in SUBMIT_PART_TOOLS or not str(extra.get("title", "")).strip():
                raise _Rejected(['action must be "continue", or "insert" with a part that has a title, a kind and an intent'])
            title = str(extra["title"]).strip()
            taken = {item.part_id for item in brief.plan}
            part_id = next(c for c in (f"extra{n}-{_slug(title)}" for n in range(1, 99)) if c not in taken)
            return PlannedPart(part_id, title, extra["kind"], f"{str(extra.get('intent', '')).strip()} (Added because: {str(raw.get('reason', '')).strip()})")

        return self._work(task, DECIDE_TOOL, accept)

    # Closing

    def summarise(self, brief: Brief, answers: list[ClickAnswer]) -> tuple[list[str], list[str]]:
        """What was solid and what was shaky, judged from the parts given and the student's clicks."""
        results = []
        for part in brief.built:
            tries = [a for a in answers if a.part_id == part.id]
            if isinstance(part, ClickCase):
                outcome = "not answered" if not tries else f"correct on try {tries[-1].attempt}" if tries[-1].correct else f"not solved in {len(tries)} tries"
                results.append(f"- [{part.kind}] {part.title}: {outcome}")
            else:
                results.append(f"- [{part.kind}] {part.title}")
        task = (
            f"{self._background(brief)}\n\nThe session is over. How it went:\n" + "\n".join(results) + "\n\n"
            "Write the closing summary with submit_summary: what was solid and what is worth another look. Short phrases, two or three of each at most. "
            "Base 'worth another look' on what they got wrong; if they got nothing wrong, say so in one phrase."
        )

        def accept(raw: dict) -> tuple[list[str], list[str]]:
            solid = [str(line).strip() for line in raw.get("solid") or [] if str(line).strip()]
            shaky = [str(line).strip() for line in raw.get("shaky") or [] if str(line).strip()]
            if not solid and not shaky:
                raise _Rejected(["give at least one phrase in solid or shaky"])
            return solid, shaky

        return self._work(task, SUBMIT_SUMMARY_TOOL, accept)


def sources_used(parts: list[Part]) -> list[Source]:
    """Every distinct source cited in these parts, in the order first used. Collected by code, not by the agent."""
    found: dict[str, Source] = {}

    def visit(value: Any) -> None:
        if hasattr(value, "source") and hasattr(value, "text"):
            found.setdefault(value.source.model_dump_json(), value.source)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, BaseModel):
            for name in type(value).model_fields:
                visit(getattr(value, name))

    visit(parts)
    return list(found.values())
