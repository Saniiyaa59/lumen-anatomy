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

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Sequence

from pydantic import BaseModel, TypeAdapter, ValidationError

from app import measure, notes
from app.agent_tools import ANSWER_STUDENT_TOOL, ASK_STUDENT_TOOL, DECIDE_TOOL, LOOKUP_TOOLS, MUST_SEE, SUBMIT_PART_TOOLS, SUBMIT_PLAN_TOOL, SUBMIT_SUMMARY_TOOL, run_lookup
from app.articles import Articles
from app.llm import LLM, Usage
from app.progress import Progress, describe_lookup
from app.region import Region
from app.session_check import check_part
from app.session_schemas import ChoiceAnswer, ClickAnswer, ClickCase, DamageSlider, Demonstration, MultipleChoice, Part, PartKind, Pulse, Scope, Source, Statement, StudentAnswer

# Shown in the terminal the backend runs in, next to uvicorn's own lines.
log = logging.getLogger("uvicorn.error")

MAX_TURNS = 24  # requests to Claude for one piece of work, lookups included
MAX_HAND_INS = 4  # times one part may be handed in before it is given up on
MAX_NOTE_FACTS = 40
MAX_QUESTIONS = 2  # questions the tutor may ask before it must plan
EXTRA_PREFIX = "extra"  # starts the id of a part the agent added after a wrong answer
MIN_QUOTE_CHARS = 20
CLICK_TOLERANCE = 0.002  # metres past the end of an answer region that still count


PART_ADAPTER: TypeAdapter[Part] = TypeAdapter(Part)

SYSTEM = """You are the tutor inside Lumen, a study tool built on a 3D anatomy model. A student says what they need to be ready for. You build a short study session that plays on the model of the {region_name}, one part at a time.

# The five kinds of part

- demonstration: the camera frames some structures, hides what is in the way and tints the ones being discussed, beside a line or two of explanation.
- pulse: a pulse runs along a vessel from one place to another, or spreads into every branch beyond a place, to show a course and its branching.
- damage_slider: the student drags a blockage along one piece of a vessel; everything beyond it greys out. Text can change as the blockage enters different zones.
- click_case: a short story about an invented patient, then "click where the problem is". The student answers by clicking the model and is graded by the exact place.
- multiple_choice: a question, optionally after a short patient story, with two to five answers to pick from. To have the student name something, highlight it and ask what it is. Without a highlight it quizzes what the model can't show, such as which wall an artery feeds or where the artery to a node comes from.

The student's request decides what a session covers; the model only decides how it can be shown. Where the topic allows, build around reasoning rather than naming: what follows if this is blocked here, and where must the problem be given these findings.

# The model

Structures are listed below as `id | name | kind | inside`. A group has no shape; it only gathers structures. A tube is a vessel with a centre line made of pieces named `<structure id>.<n>`; piece `.0` is the trunk and the others are branches. A place on a vessel is a piece and a distance along it in metres.

{structure_list}

What this model cannot show: which part of an organ's wall a vessel supplies (there are no territories), anything that moves, and anything not in the list above. Some branches are drawn but have no name of their own; `branches_of` marks them as unnamed. Say so plainly when a request depends on something the model lacks.

# Rules that are checked

1. Never state a distance, the order of branches, or what lies beyond a point from memory. Ask the tools. All distances are metres.
2. Every statement the student reads needs a source:
   - atlas: the article's key and a quote copied word for word from it that says what your statement says. Search, then read the article, then quote.
   - notes: when the student gave notes, either the number of a fact listed from them, or a page and a quote copied word for word from that page. Look in the notes before the atlas: search_notes finds what the listed facts left out, and read_notes_page gives a whole page. Prefer the notes. If the notes and the atlas disagree, follow the notes and say that they differ.
   - model: only for what you measured with the tools, such as a length or where a branch leaves.
   A statement says only what its source says. Don't add to it what the session will do next, what a later part covers, or a fact from somewhere else: give a further fact its own statement and source, and leave remarks about the session out, since every statement must have a source.
3. The student must be able to see what a part is about when it opens. The code sees to this: leave `view.side` out, put in `view.look_at` what the camera should frame, and the code picks the side and adds what is in front to `hide`. It never hides the part's subject, and hides what you frame only when it must. Don't mention the side in what you write unless you chose it with `find_view`. Give a side yourself only to insist on it; if too little shows from there, the code picks another.
4. A click case needs exactly one right place. Give findings that only that place explains, and check with `beyond` that they match what the model shows. Add near misses for the wrong clicks a student is likely to make, each with its own short explanation. A near miss may not overlap the answer.
5. A multiple-choice question has exactly one right answer, and neither the question nor the story may contain its words. The wrong answers are things a student could believe: the same kind of thing as the right one (all arteries, say), never silly. Each answer's feedback says why it is right or wrong and has a source like any statement. The right answer's feedback may be shown after the student has picked wrong ones, so it does not begin with "Right" or "Correct": it just says why that answer is the one.

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
class Turn:
    """One line of what the tutor and the student said to each other, before the plan or during the session."""

    who: Literal["tutor", "student"]
    text: str


@dataclass
class Question:
    """What the agent wants to ask the student before it can plan."""

    text: str
    options: list[str]


@dataclass
class ChatAnswer:
    """The agent's answer to something the student said mid-session."""

    statements: list[Statement]
    point_to: list[str]  # structures to select on the model
    new_plan: list["PlannedPart"] | None  # replaces the parts not yet given, when the agent changes direction


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
    notes_file: str | None = None  # the notes' file name, when the student gave notes
    pages: list[str] = field(default_factory=list)  # the text of each page of the notes, for search_notes; empty if it couldn't be read
    conversation: list[Turn] = field(default_factory=list)  # what the tutor and student said, oldest first
    scope: Scope | None = None
    plan: list[PlannedPart] = field(default_factory=list)
    built: list[Part] = field(default_factory=list)  # parts already handed to the student, in order


def _squash(text: str) -> str:
    """Text with case and spacing ironed out, for comparing a quote with its article."""
    return re.sub(r"\s+", " ", text).strip().lower()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:32] or "part"


def _read_parts(parts: Any, make_id: Callable[[int, str], str]) -> tuple[list["PlannedPart"], list[str]]:
    """Planned parts from what the agent handed in, with the problems found. `make_id` gives each its part id."""
    if not isinstance(parts, list) or not 1 <= len(parts) <= 5:
        return [], ["parts: plan between one and five parts"]
    planned: list[PlannedPart] = []
    problems: list[str] = []
    for index, item in enumerate(parts):
        kind = item.get("kind") if isinstance(item, dict) else None
        title = str(item.get("title", "")).strip() if isinstance(item, dict) else ""
        if kind not in SUBMIT_PART_TOOLS:
            problems.append(f"parts[{index}].kind: must be one of {', '.join(SUBMIT_PART_TOOLS)}")
        elif not title:
            problems.append(f"parts[{index}].title: must not be empty")
        else:
            planned.append(PlannedPart(make_id(index, title), title, kind, str(item.get("intent", "")).strip()))
    return planned, problems


class Agent:
    def __init__(self, llm: LLM, region: Region, articles: Articles, usage: Usage | None = None):
        self.llm = llm
        self.region = region
        self.articles = articles
        self.usage = usage or Usage()
        self.progress = Progress()  # what it is doing now, for the student to read while they wait
        listing = [f"{group.id} | {group.name} | group | {group.parent or '-'}" for group in region.groups.values()]
        listing += [f"{s.id} | {s.name} | {s.kind} | {s.parent or '-'}" for s in region.structures.values()]
        self.system = SYSTEM.format(region_name=region.name.lower(), structure_list="\n".join(listing))

    # Talking to Claude

    def _ask(self, messages: list[dict], tools: list[dict] | None = None) -> tuple[Any, float]:
        """One request. Returns Claude's reply and how many seconds it took."""
        started = time.monotonic()
        response = self.llm.ask(system=self.system, messages=messages, tools=tools)
        seconds = time.monotonic() - started
        self.usage.add(getattr(response, "usage", None), seconds)
        return response, seconds

    def _timed(self, stage: str, response: Any, claude: float, here: float, did: str) -> None:
        """Note how long one request took, and what came of it, in the session's usage and the terminal.

        `claude` is the wait for Claude; `here` is the backend's own work on the reply
        (lookups, checking a hand-in). `did` says what the reply was: lookups (and
        which), a hand-in that was accepted or rejected, or text with no tool call.
        """
        used = getattr(response, "usage", None)
        output = getattr(used, "output_tokens", 0) or 0
        fresh = getattr(used, "input_tokens", 0) or 0
        cached = getattr(used, "cache_read_input_tokens", 0) or 0
        written = getattr(used, "cache_creation_input_tokens", 0) or 0
        total = fresh + cached + written
        timing = {
            "at": round(time.time(), 2),  # when the reply came, so overlapping builders can be lined up
            "stage": stage,
            "claude_seconds": round(claude, 2),
            "here_seconds": round(here, 2),
            "did": did,
            "output_tokens": output,
            "input_tokens": total,
            "cached_share": round(cached / total, 2) if total else 0.0,
        }
        self.usage.record(timing)
        log.info(
            "claude %5.1fs + here %4.1fs | %s | %s | out %s tok, in %s tok (%d%% cached)",
            claude, here, stage, did, f"{output:,}", f"{total:,}", round(100 * timing["cached_share"]),
        )

    def _work(
        self,
        task: str,
        hand_in: dict[str, Any],
        accept: Callable[[dict], Any],
        also: Sequence[tuple[dict[str, Any], Callable[[dict], Any]]] = (),
        stage: str | None = None,
        brief: "Brief | None" = None,
        doing: str | None = None,
    ) -> Any:
        """Let Claude work on a task with the lookup tools until what it hands in is accepted.

        `also` offers other ways to finish, each with its own check. The main hand-in
        stays last in the tool list. `stage` names the task in the timings (the
        hand-in tool's name if not given). `brief` gives the lookups the student's notes.
        `doing` says what the work is, for the student while they wait (see app/progress.py).
        """
        stage = stage or hand_in["name"]
        self.progress.begin(stage, doing or "Thinking")
        try:
            return self._work_on(task, hand_in, accept, also, stage, brief)
        finally:
            self.progress.end(stage)

    def _work_on(
        self,
        task: str,
        hand_in: dict[str, Any],
        accept: Callable[[dict], Any],
        also: Sequence[tuple[dict[str, Any], Callable[[dict], Any]]],
        stage: str,
        brief: "Brief | None",
    ) -> Any:
        """The loop behind _work: ask, run lookups, check hand-ins, until one is accepted."""
        accepts = {hand_in["name"]: accept, **{tool["name"]: check for tool, check in also}}
        tools = [*LOOKUP_TOOLS, *(tool for tool, _ in also), hand_in]
        finish = " or ".join(accepts)
        messages: list[dict] = [{"role": "user", "content": task}]
        problems = ["nothing was handed in"]
        hand_ins = 0
        began = time.monotonic()
        claude_total = 0.0

        def done(how: str, requests: int) -> None:
            took = time.monotonic() - began
            rejected = hand_ins - 1 if how == "accepted" else hand_ins
            log.info("%s: %s after %d requests, %.1fs (Claude %.1fs, here %.1fs, %d rejected)", stage, how, requests, took, claude_total, took - claude_total, rejected)

        for turn in range(1, MAX_TURNS + 1):
            response, claude = self._ask(messages, tools)
            claude_total += claude
            handled = time.monotonic()
            messages.append({"role": "assistant", "content": response.content})
            calls = [block for block in response.content if block.type == "tool_use"]
            if not calls:
                self._timed(stage, response, claude, time.monotonic() - handled, "text, no tool call")
                messages.append({"role": "user", "content": f"Finish by calling {finish}."})
                continue
            results = []
            lookups = []
            for call in calls:
                failed = False
                if call.name in accepts:
                    hand_ins += 1
                    self.progress.step(stage, "Checking it against the model and the sources")
                    try:
                        accepted = accepts[call.name](call.input)
                    except _Rejected as rejected:
                        problems = rejected.problems
                        content = "Not accepted. Fix these and hand it in again:\n- " + "\n- ".join(problems)
                        failed = True
                        self.progress.step(stage, "Fixing something the checks found")
                    else:
                        self._timed(stage, response, claude, time.monotonic() - handled, f"{call.name} accepted")
                        done("accepted", turn)
                        return accepted
                else:
                    lookups.append(call.name)
                    self.progress.step(stage, describe_lookup(call.name, call.input, self.region, self.articles))
                    try:
                        content = run_lookup(call.name, call.input, self.region, self.articles, brief.pages if brief else [])
                    except (ValueError, TypeError) as error:
                        content, failed = str(error), True
                results.append({"type": "tool_result", "tool_use_id": call.id, "content": content, **({"is_error": True} if failed else {})})
            did = [f"lookups: {', '.join(lookups)}"] if lookups else []
            # What was wrong, cut short: enough to see in the timings which checks cost retries.
            why = "; ".join(problem if len(problem) <= 160 else problem[:157] + "..." for problem in problems[:3])
            did += [f"{name} rejected: {why}" for name in (c.name for c in calls) if name in accepts]
            self._timed(stage, response, claude, time.monotonic() - handled, "; ".join(did))
            if hand_ins >= MAX_HAND_INS:
                done("given up", turn)
                raise AgentError(problems)
            # Every result of a turn goes back in one message.
            messages.append({"role": "user", "content": results})
        done("ran out of turns", MAX_TURNS)
        raise AgentError(["ran out of turns", *problems])

    def _background(self, brief: Brief) -> str:
        """What the session is for and what has happened so far, as text for a task."""
        lines = [f"The student asked: {brief.request}" if brief.request else "The student opened the model to explore it; they have not asked for anything yet."]
        if brief.conversation:
            lines.append("Then:")
            lines += [f"- {'You said' if turn.who == 'tutor' else 'The student said'}: {turn.text}" for turn in brief.conversation]
        lines.append("")
        if brief.facts:
            lines.append("Facts from the student's notes (cite one as source type notes with its number):")
            lines += [f"{fact.number}. {fact.text} (page {fact.page})" for fact in brief.facts]
        if brief.pages:
            lines.append(f"The notes have {len(brief.pages)} pages. Search them with search_notes for anything these facts leave out.")
        if not brief.facts and not brief.pages:
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
        self.progress.begin("notes", "Reading your notes")
        try:
            return self._read_notes(request, pdf_base64, filename)
        finally:
            self.progress.end("notes")

    def _read_notes(self, request: str, pdf_base64: str, filename: str) -> list[NoteFact]:
        response, claude = self._ask(
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
        self._timed("notes", response, claude, 0.0, f"read {len(facts)} facts")
        return facts

    # Scope and plan

    def plan(self, brief: Brief) -> Question | ChatAnswer | None:
        """Plan a session from what the student asked, ask them something first, or simply answer them.

        Fills `brief.scope` and `brief.plan` and returns None; or returns a question
        for the student; or returns an answer, when what they said was a question
        rather than a request to be taught or tested. With a question or an answer
        the plan stays empty. Once MAX_QUESTIONS have been asked, the agent can
        no longer ask.
        """
        asked = sum(1 for turn in brief.conversation if turn.who == "tutor")
        may_ask = asked < MAX_QUESTIONS
        answering = (
            "First decide what they want. If they ask a question (\"how does blood flow in the aorta?\", \"what is this?\"), "
            "answer it with answer_student, as you would mid-session: no session is planned, and they can go on exploring the model and asking. "
            "Plan a session only when they ask to be taught, prepared, revised or quizzed on something.\n\n"
        )
        if may_ask:
            deciding = answering + (
                "If they want a session, decide whether you know what to cover. Their words, their replies and their notes decide the topic. "
                "If they name a topic, or their notes show what it is, plan for that. "
                "If they don't (for example \"help me with my exam tomorrow\" with no notes), do not guess: ask with ask_student, "
                "one short question with two to four answers drawn from what this model can show. "
                "Also ask if their request is something the model can't show at all, offering the nearest things it can.\n\n"
            )
        else:
            deciding = answering + (
                "You have asked enough questions; if they want a session, plan it now from what they have said. "
                "If you still had to assume something, say what in words_only.\n\n"
            )
        task = (
            f"{self._background(brief)}\n\n{deciding}"
            "Plan two to five parts that build on each other, chosen for this request: what someone revising this topic most needs. "
            "Pick the kinds that suit the topic. A damage_slider or click_case fits where a blockage teaches something; for other topics, demonstrations and pulses may be all you need. "
            "A multiple_choice question tests what can only be explained in words, or asks the student to name a highlighted structure. "
            "Look at the structures you intend to use with `describe` and `branches_of` first, so the plan fits what the model has. "
            "Hand the plan in with submit_plan."
        )

        def accept_question(raw: dict) -> Question:
            text = str(raw.get("question", "")).strip()
            options = [str(option).strip() for option in raw.get("options") or [] if str(option).strip()]
            problems = []
            if not text:
                problems.append("question: must not be empty")
            if len(options) > 4:
                problems.append("options: give at most four")
            if problems:
                raise _Rejected(problems)
            return Question(text=text, options=options)

        def accept(raw: dict) -> None:
            parts = raw.get("parts")
            if not isinstance(parts, list) or not 2 <= len(parts) <= 5:
                raise _Rejected(["parts: plan between two and five parts"])
            planned, problems = _read_parts(parts, lambda index, title: f"p{index + 1}-{_slug(title)}")
            try:
                scope = Scope(can_show=raw.get("can_show") or [], words_only=raw.get("words_only") or [])
            except ValidationError:
                problems.append("can_show and words_only: must be lists of non-empty sentences")
            if problems:
                raise _Rejected(problems)
            brief.scope, brief.plan = scope, planned

        def accept_answer(raw: dict) -> ChatAnswer:
            return self._accept_answer(brief, {**raw, "new_plan": None})

        also = [(ASK_STUDENT_TOOL, accept_question)] if may_ask else []
        return self._work(task, SUBMIT_PLAN_TOOL, accept, also=[*also, (ANSWER_STUDENT_TOOL, accept_answer)], stage="plan", brief=brief, doing="Planning your session")

    # Building a part

    def build(self, brief: Brief, item: PlannedPart) -> Part:
        """Build one planned part, checked. Raises AgentError if nothing acceptable came after several tries."""
        task = (
            f"{self._background(brief)}\n\n"
            f'Build this part now: [{item.kind}] "{item.title}". What it should teach: {item.intent}\n\n'
            f"Look up what you need, making all the lookups you already know you need in the same turn, then hand it in with {SUBMIT_PART_TOOLS[item.kind]['name']}. Leave view.side out: the code chooses the view."
        )
        return self._work(task, SUBMIT_PART_TOOLS[item.kind], lambda raw: self._accept_part(brief, item, raw), stage=f"part {item.part_id}", brief=brief, doing=f"Building “{item.title}”")

    def _source(self, brief: Brief, evidence: Any, path: str, problems: list[str]) -> dict | None:
        """Turn the agent's evidence for a statement into a session source, or record why it is not good enough."""
        kind = evidence.get("type") if isinstance(evidence, dict) else None
        if kind == "model":
            return {"type": "model"}
        if kind == "notes":
            if evidence.get("page") is not None:
                page, quote = evidence.get("page"), str(evidence.get("quote", ""))
                if not brief.pages:
                    problems.append(f"{path}.page: the notes' pages can't be quoted in this session; cite a fact by its number")
                elif not isinstance(page, int) or not 1 <= page <= len(brief.pages):
                    problems.append(f"{path}.page: the notes have pages 1 to {len(brief.pages)}")
                elif len(quote.strip()) < MIN_QUOTE_CHARS:
                    problems.append(f"{path}.quote: give a full sentence copied from that page of the notes")
                elif not notes.quoted_on(brief.pages, page, quote):
                    problems.append(f"{path}.quote: this is not on page {page} of the notes word for word; read the page with read_notes_page and copy the sentence exactly")
                else:
                    return {"type": "notes", "file": brief.notes_file or "notes.pdf", "page": page}
                return None
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
        if isinstance(draft.get("view"), dict):
            draft["view"].setdefault("side", None)  # left out: the code chooses it below
            draft["view"]["look_at"] = self._ungroup(draft["view"].get("look_at"))
        if "highlight" in draft:
            draft["highlight"] = self._ungroup(draft["highlight"])
        if item.kind == "click_case" and isinstance(draft.get("answer"), dict):
            draft["answer"]["tolerance"] = CLICK_TOLERANCE
        if item.kind == "multiple_choice":
            draft.setdefault("highlight", [])
            draft.setdefault("story", None)
        try:
            part = PART_ADAPTER.validate_python(draft)
        except ValidationError as error:
            # The first step of each location is the kind of part, which the agent already knows.
            shape = [f"{'.'.join(['part', *(str(step) for step in e['loc'][1:])])}: {e['msg']}" for e in error.errors()]
            raise _Rejected([*problems, *shape]) from None
        problems += check_part(part, self.region, self.articles)
        if isinstance(part, ClickCase):
            # A whole vessel in the answer makes a click anywhere on it right, so the stretch means nothing.
            vessels = {self.region.vessel_of(r.piece) for r in part.answer.regions if r.piece in self.region.pieces}  # an unknown piece is reported above
            problems += [
                f"part.answer.structures: {structure_id} is the vessel the answer's regions lie on, so listing it makes a click anywhere on it right. Leave it out and let the regions say where."
                for structure_id in part.answer.structures
                if structure_id in vessels
            ]
        if isinstance(part, MultipleChoice):
            problems += _gives_away(part)
        if not problems:
            part, seeing = self._settle_view(part)
            problems += seeing
        if problems:
            raise _Rejected(problems)
        return part

    def _ungroup(self, ids: Any) -> Any:
        """A list of ids with each group replaced by the structures in it, which is what framing or tinting a group means.

        Anything else, including an id that is neither, is left for the checks to report.
        """
        if not isinstance(ids, list):
            return ids
        found: list[Any] = []
        for entry in ids:
            for item in self.region.structures_under(entry) if isinstance(entry, str) and entry in self.region.groups else [entry]:
                if item not in found:
                    found.append(item)
        return found

    def _settle_view(self, part: Part) -> tuple[Part, list[str]]:
        """Make sure the student can see what this part is about when it opens.

        A side the agent gave is kept if enough shows from it with its hide list.
        Otherwise, or when it gave none, the code chooses the side and adds to the
        hide list (measure.choose_view), preferring the agent's side. Returns the
        part, with its view settled, and the problems if no side shows enough.
        """
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
        elif isinstance(part, (Demonstration, MultipleChoice)):
            structures = list(part.highlight)  # a question with nothing highlighted needs no particular view
            what = "the highlighted structures"
        if not stretches and not structures:
            return part, []
        need = MUST_SEE[part.kind]
        given = part.view.side
        if given is not None:
            seen = measure.what_hides(self.region, stretches=stretches, structures=structures, look_at=part.view.look_at, hidden=part.hide, sides=[given])
            if seen.sides[0].visible >= need:
                return part, []
        choice = measure.choose_view(self.region, need, stretches=stretches, structures=structures, look_at=part.view.look_at, hidden=part.hide, prefer=given)
        if choice.side is None:
            best = choice.sides[0]
            stuck = ", ".join(best.still_in_front) or "nothing that may be hidden"
            return part, [
                f"part.view: {what} can't be seen well enough from any side ({need:.0%} must show). "
                f"The best is the {best.side}, showing {best.visible:.0%} even after hiding {', '.join(best.added) or 'nothing'}. "
                f"Still in front: {stuck}, which is part of what the part is about and so is never hidden. Make the subject smaller: fewer structures, or a stretch of a vessel instead of the whole of it."
            ]
        log.info("%s: view chosen by the code: %s%s, hiding %s (%.0f%% shows)", part.id, choice.side, f" (asked for {given})" if given and given != choice.side else "", choice.added or "nothing more", 100 * choice.visible)
        settled = part.model_copy(update={"view": part.view.model_copy(update={"side": choice.side}), "hide": choice.hide})
        return settled, []

    # Talking with the student mid-session

    def chat(self, brief: Brief, text: str, selected: list[str], on_screen: str | None) -> ChatAnswer:
        """Answer what the student said during the session, and change the rest of the plan if that is called for.

        `selected` is what they have selected on the model; `on_screen` the title of the part they are on.
        Does not record the exchange in the brief; the caller does, once it has been accepted.
        """
        context = []
        if on_screen:
            context.append(f'They are on the part "{on_screen}".')
        if selected:
            context.append("They have selected on the model: " + ", ".join(f"{self.region.name_of(i)} ({i})" for i in selected) + ".")
        task = (
            f"{self._background(brief)}\n\n"
            + (" ".join(context) + "\n" if context else "")
            + f"The student says: {text}\n\n"
            "Answer them with answer_student, briefly and in plain words. Look things up first; every statement needs a source, as in a part. "
            "If they point at something (\"this\", \"here\"), they mean what they have selected. "
            "Select structures with point_to when it helps them see what you mean. "
            "If they ask to go another way (another topic, more practice, skip ahead, something easier), or their question shows the plan no longer fits, "
            "give new_plan: it replaces every part they have not been given yet. Otherwise leave the plan alone. "
            "If there is no plan yet, they are exploring the model: give new_plan only when they ask to be taught, prepared or quizzed."
        )
        return self._work(task, ANSWER_STUDENT_TOOL, lambda raw: self._accept_answer(brief, raw), stage="chat", brief=brief, doing="Answering you")

    def _accept_answer(self, brief: Brief, raw: dict) -> ChatAnswer:
        """Check an answer to the student: its statements' sources, what it points to, and any new plan."""
        changes = sum(1 for turn in brief.conversation if turn.who == "student")
        problems: list[str] = []
        drafts = raw.get("statements")
        if not isinstance(drafts, list) or not 1 <= len(drafts) <= 4:
            raise _Rejected(["statements: give one to four"])
        checked = self._with_sources(brief, drafts, "statements", problems)
        statements: list[Statement] = []
        for index, draft in enumerate(checked):
            try:
                statements.append(Statement.model_validate(draft))
            except ValidationError:
                problems.append(f"statements[{index}]: needs non-empty text and a source")
        point_to = [str(i) for i in raw.get("point_to") or []]
        problems += [f'point_to: "{i}" is not a structure on this model' for i in point_to if i not in self.region.structures]
        new_plan = None
        if raw.get("new_plan"):
            taken = {item.part_id for item in brief.plan}
            new_plan, plan_problems = _read_parts(raw["new_plan"], lambda index, title: f"c{changes + 1}-{index + 1}-{_slug(title)}")
            problems += plan_problems
            problems += [f"new_plan: part id {item.part_id} is already used" for item in new_plan if item.part_id in taken]
        if problems:
            raise _Rejected(problems)
        return ChatAnswer(statements=statements, point_to=point_to, new_plan=new_plan)

    # Replanning

    def decide(self, brief: Brief, case: ClickCase | MultipleChoice, answers: Sequence[StudentAnswer]) -> PlannedPart | None:
        """After a case or question the student got wrong at least once: carry on, or put one extra part first. Returns the extra part, if any."""
        tries = []
        for answer in answers:
            outcome = "correct" if answer.correct else "wrong"
            if isinstance(answer, ChoiceAnswer):
                picked = case.options[answer.choice].text if isinstance(case, MultipleChoice) and answer.choice < len(case.options) else f"option {answer.choice}"
                tries.append(f"- try {answer.attempt}: picked \"{picked}\"; {outcome}")
            else:
                where = f"{answer.piece} at {answer.at:.4f} m" if answer.piece is not None and answer.at is not None else "not on a vessel"
                tries.append(f"- try {answer.attempt}: {self.region.name_of(answer.structure_id)} ({where}); {outcome}")
        if isinstance(case, MultipleChoice):
            right = next(option.text for option in case.options if option.correct)
            what = f'the question "{case.title}"'
            asked = (f"Story: {case.story}\n" if case.story else "") + f"Question: {case.question}\n" + f"Answers offered: {'; '.join(option.text for option in case.options)}. Right answer: {right}.\n"
            how = "Their picks"
        else:
            regions = ", ".join(f"{r.piece} from {r.start} to {r.to}" for r in case.answer.regions) or "none"
            what = f'the case "{case.title}"'
            asked = f"Story: {case.story}\nQuestion: {case.question}\nRight answer: regions {regions}; structures {', '.join(case.answer.structures) or 'none'}.\n"
            how = "Their clicks"
        remaining = [item for item in brief.plan if item.part_id not in {part.id for part in brief.built}]
        task = (
            f"{self._background(brief)}\n\n"
            f"The student has just finished {what}.\n"
            f"{asked}"
            f"{how}:\n" + "\n".join(tries) + "\n\n"
            "Still to come: " + (", ".join(f"[{item.kind}] {item.title}" for item in remaining) or "nothing; the summary is next") + "\n\n"
            "Decide what the wrong answers say about what they have not understood. If one extra part before the rest would fix it, such as a demonstration of the point they missed or an easier question, ask for it. "
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
            part_id = next(c for c in (f"{EXTRA_PREFIX}{n}-{_slug(title)}" for n in range(1, 99)) if c not in taken)
            return PlannedPart(part_id, title, extra["kind"], f"{str(extra.get('intent', '')).strip()} (Added because: {str(raw.get('reason', '')).strip()})")

        return self._work(task, DECIDE_TOOL, accept, stage=f"decide after {case.id}", brief=brief, doing="Deciding what to do about your answers")

    # Closing

    def summarise(self, brief: Brief, answers: Sequence[StudentAnswer]) -> tuple[list[str], list[str]]:
        """What was solid and what was shaky, judged from the parts given and the student's clicks."""
        results = []
        for part in brief.built:
            tries = [a for a in answers if a.part_id == part.id]
            if isinstance(part, (ClickCase, MultipleChoice)):
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

        return self._work(task, SUBMIT_SUMMARY_TOOL, accept, stage="summary", brief=brief, doing="Writing your summary")


def _gives_away(question: MultipleChoice) -> list[str]:
    """Problems if the question or its story contains the words of the right answer, so it answers itself."""
    right = next(option.text for option in question.options if option.correct)
    asked = _squash(f"{question.story or ''} {question.question}")
    if re.search(rf"\b{re.escape(_squash(right))}\b", asked):  # whole words: "LAD" is not in "bladder"
        return [f'part.question: the question or story says "{right}", the right answer, so it gives itself away. Describe it by findings or by where it is instead.']
    return []


def sources_used(parts: list[Part]) -> list[Source]:
    """Every distinct source cited in these parts, in the order first used. Collected by code, not by the agent.

    Atlas sources count as one per page linked: several atlas entries hold the same
    Wikipedia page, and the student sees them named by that page.
    """
    found: dict[str, Source] = {}

    def visit(value: Any) -> None:
        if hasattr(value, "source") and hasattr(value, "text"):
            source = value.source
            key = f"atlas page {source.url}" if source.type == "atlas" and source.url else source.model_dump_json()
            found.setdefault(key, source)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, BaseModel):
            for name in type(value).model_fields:
                visit(getattr(value, name))

    visit(parts)
    return list(found.values())
