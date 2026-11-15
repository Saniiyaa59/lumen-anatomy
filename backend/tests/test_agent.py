"""The session agent, driven by scripted replies in place of Claude.

No test here talks to the API. `Scripted` hands back prepared replies, chosen by
which hand-in tool the agent offered, so the order holds even when parts are
built on background threads.
"""

import copy
import json
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import sessions
from app.agent import MAX_HAND_INS, Agent, AgentError, Brief, NoteFact, PlannedPart, sources_used
from app.agent_tools import LOOKUP_TOOLS, SUBMIT_PART_TOOLS, run_lookup
from app.articles import get_articles
from app.llm import LLMError, Usage
from app.main import app
from app.region import get_region
from app.session_schemas import ClickAnswer, ClickCase, Demonstration

region = get_region()
articles = get_articles()
client = TestClient(app)

LAD = "anterior_interventricular_artery"
LCA = "left_coronary_artery"
CIRCUMFLEX = "circumflex_artery_of_heart"
RCA = "right_coronary_artery"

SEPTAL_QUOTE = "Septals originate from the LAD at 90 degrees to the surface of the heart, perforating and supplying the anterior 2/3rds of the interventricular septum."
CIRCUMFLEX_QUOTE = "The LCX supplies the posterolateral left ventricle and the anterolateral papillary muscle."
RCA_QUOTE = "It travels down the right coronary sulcus, towards the crux of the heart."


def lad_source(quote=SEPTAL_QUOTE):
    return {"type": "atlas", "article": "Left anterior descending artery", "quote": quote}


def case_draft():
    """A click case as the agent would hand it in: the sample's case, with evidence in place of finished sources."""
    return {
        "title": "Case: find the blockage",
        "view": {"look_at": [LCA, LAD, CIRCUMFLEX], "side": "left"},
        "hide": ["left_atrium", "pulmonary_trunk", "cardiac_veins"],
        "story": "A man has sudden chest pain. The whole front of the wall between the ventricles has lost its blood supply.",
        "question": "Click where the blockage is.",
        "answer": {"regions": [{"piece": f"{LAD}.0", "from": 0, "to": 0.0465}], "structures": []},
        "feedback": {
            "correct": {"text": "Right. The septal branches supply the front of the septum.", "source": lad_source()},
            "wrong": {"text": "Not there. Find the artery whose branches supply the septum.", "source": lad_source()},
            "near_misses": [
                {
                    "regions": [{"piece": f"{LAD}.0", "from": 0.0465, "to": 0.1145}],
                    "structures": [],
                    "statement": {"text": "Right artery, but a septal branch has already left by here.", "source": {"type": "model"}},
                },
                {
                    "regions": [],
                    "structures": [CIRCUMFLEX],
                    "statement": {"text": "This artery supplies the back and side.", "source": {"type": "atlas", "article": "Circumflex artery of heart", "quote": CIRCUMFLEX_QUOTE}},
                },
            ],
        },
    }


def demo_draft(title="Where the right coronary artery runs"):
    return {
        "title": title,
        "view": {"look_at": [RCA], "side": "anterior"},
        "hide": [],
        "highlight": [RCA],
        "statements": [{"text": "The right coronary artery runs down the right coronary sulcus.", "source": {"type": "atlas", "article": "Right coronary artery", "quote": RCA_QUOTE}}],
    }


CASE_ITEM = PlannedPart("p2-case", "Case: find the blockage", "click_case", "Place a blockage before the first septal branch.")
DEMO_ITEM = PlannedPart("p1-demo", "Where the right coronary artery runs", "demonstration", "Show its course.")

# Stand-ins for Claude's replies

_ids = iter(range(10_000))


def call(name, **arguments):
    return SimpleNamespace(type="tool_use", id=f"call{next(_ids)}", name=name, input=arguments)


def says(text, citations=None):
    return SimpleNamespace(type="text", text=text, citations=citations)


def reply(*blocks):
    used = SimpleNamespace(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0, cache_creation_input_tokens=0)
    return SimpleNamespace(content=list(blocks), stop_reason="tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn", usage=used)


class Scripted:
    """Replays replies. Each is filed under the hand-in tool offered with the request ("notes" when there are no tools)."""

    def __init__(self, **replies):
        self.replies = {name: list(queue) for name, queue in replies.items()}
        self.asked = []  # (hand-in tool, the messages as they were when asked)
        self.lock = threading.Lock()

    def ask(self, *, system, messages, tools=None):
        stage = tools[-1]["name"] if tools else "notes"
        with self.lock:
            self.asked.append((stage, copy.copy(messages)))
            queue = self.replies.get(stage)
            if not queue:
                raise AssertionError(f"no scripted reply left for {stage}")
            step = queue.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    def last_results(self, stage):
        """The tool results the agent sent back the last time it asked at this stage."""
        messages = [m for s, m in self.asked if s == stage][-1]
        return messages[-1]["content"]


def agent_with(**replies):
    llm = Scripted(**replies)
    return Agent(llm, region, articles, Usage()), llm


# The lookup tools


def test_every_lookup_tool_runs_on_the_heart_and_writes_stretches_as_a_session_does():
    described = json.loads(run_lookup("describe", {"id": LAD}, region, articles))
    assert described["name"] == "Anterior interventricular artery"
    branches = json.loads(run_lookup("branches_of", {"piece": f"{LAD}.0"}, region, articles))
    assert branches[0]["at"] == pytest.approx(0.0465, abs=1e-4)
    cut = json.loads(run_lookup("beyond", {"piece": f"{LAD}.0", "at": 0.03}, region, articles))
    assert set(cut["stretches"][0]) == {"piece", "from", "to"}
    path = json.loads(run_lookup("route", {"from_piece": f"{LCA}.0", "from_at": 0, "to_piece": f"{CIRCUMFLEX}.0", "to_at": 0.05}, region, articles))
    assert len(path["segments"]) == 2
    seen = json.loads(run_lookup("what_hides", {"stretches": [{"piece": f"{LAD}.0", "from": 0, "to": 0.0465}], "sides": ["left"]}, region, articles))
    assert seen["sides"][0]["blockers"][0]["structure"] == "left_atrium"
    found = json.loads(run_lookup("search_articles", {"query": "coronary dominance"}, region, articles))
    assert found[0]["article"] == "Coronary circulation"
    read = json.loads(run_lookup("read_article", {"article": "Left coronary artery"}, region, articles))
    assert "bifurcates" in read["text"]


def test_a_long_article_is_cut_with_a_note_and_a_lookup_that_cannot_run_says_why():
    assert "The article continues" in json.loads(run_lookup("read_article", {"article": "Heart"}, region, articles))["text"]
    with pytest.raises(ValueError, match="not an article"):
        run_lookup("read_article", {"article": "Spleen of the heart"}, region, articles)
    with pytest.raises(ValueError, match="needs 'piece'"):
        run_lookup("branches_of", {}, region, articles)
    with pytest.raises(ValueError, match="not a centre-line piece"):
        run_lookup("branches_of", {"piece": "aorta.9"}, region, articles)
    with pytest.raises(ValueError, match="no tool called"):
        run_lookup("delete_everything", {}, region, articles)


def test_tool_definitions_are_well_formed():
    tools = [*LOOKUP_TOOLS, *SUBMIT_PART_TOOLS.values()]
    assert len({tool["name"] for tool in tools}) == len(tools)
    for tool in tools:
        assert tool["description"] and tool["input_schema"]["type"] == "object"
        json.dumps(tool)  # must be plain data


# Planning


def test_plan_looks_things_up_then_hands_in_a_plan():
    good = {
        "can_show": ["The course of the coronary arteries"],
        "words_only": ["Which wall each artery supplies"],
        "parts": [
            {"title": "Where the arteries run", "kind": "demonstration", "intent": "Show both."},
            {"title": "Case: find the blockage", "kind": "click_case", "intent": "Proximal blockage."},
        ],
    }
    agent, llm = agent_with(
        submit_plan=[
            reply(says("Let me look."), call("describe", id=LAD), call("branches_of", piece=f"{LAD}.0")),
            reply(call("submit_plan", can_show=["x"], words_only=[], parts=[{"title": "Only a demo", "kind": "demonstration", "intent": ""}])),
            reply(call("submit_plan", **good)),
        ]
    )
    brief = Brief(request="Prepare me on the blood supply of the heart")
    agent.plan(brief)

    assert [(p.part_id, p.kind) for p in brief.plan] == [("p1-where-the-arteries-run", "demonstration"), ("p2-case-find-the-blockage", "click_case")]
    assert brief.scope.words_only == ["Which wall each artery supplies"]
    assert agent.usage.calls == 3
    # Both lookups came back in one message, with real data.
    first_results = llm.asked[1][1][-1]["content"]
    assert [r["type"] for r in first_results] == ["tool_result", "tool_result"]
    assert "Septal branches" in first_results[1]["content"]
    # The plan with too few parts was sent back with the reason.
    rejected = llm.asked[2][1][-1]["content"][0]
    assert rejected["is_error"] is True and "between two and five" in rejected["content"]


def test_the_instructions_list_the_model_and_the_task_carries_the_request_and_notes():
    agent, llm = agent_with(submit_plan=[reply(call("submit_plan", can_show=[], words_only=[], parts=[{"title": "A", "kind": "pulse", "intent": ""}, {"title": "B", "kind": "click_case", "intent": ""}]))])
    assert f"{LAD} | Anterior interventricular artery | tube | {LCA}" in agent.system
    brief = Brief(request="Prepare me on coronary dominance", facts=[NoteFact(1, "The RCA is dominant in most people.", "notes.pdf", 4, "RCA dominant in 70%")])
    agent.plan(brief)
    task = llm.asked[0][1][0]["content"]
    assert "Prepare me on coronary dominance" in task
    assert "1. The RCA is dominant in most people. (page 4)" in task


# Building a part


def test_a_sound_case_is_accepted_and_finished_off_by_code():
    agent, _ = agent_with(submit_click_case=[reply(call("submit_click_case", **case_draft()))])
    part = agent.build(Brief(request="x"), CASE_ITEM)

    assert isinstance(part, ClickCase)
    assert (part.id, part.answer.tolerance) == ("p2-case", 0.002)
    # The agent gave a quote; the link was filled in from the article, not by the agent.
    assert part.feedback.correct.source.model_dump() == {
        "type": "atlas",
        "article": "Left anterior descending artery",
        "url": "https://en.wikipedia.org/wiki/Left_anterior_descending_artery",
    }
    assert part.feedback.near_misses[0].statement.source.type == "model"


@pytest.mark.parametrize(
    ("spoil", "reason"),
    [
        (lambda d: d["feedback"]["correct"].update(source=lad_source("The septal branches supply most of the septum of the heart.")), "word for word"),
        (lambda d: d["feedback"]["correct"].update(source={"type": "atlas", "article": "Septal arteries", "quote": SEPTAL_QUOTE}), "is not an article"),
        (lambda d: d["feedback"]["correct"].update(source=lad_source("Septals")), "full sentence"),
        (lambda d: d["feedback"]["wrong"].update(source={"type": "notes", "fact": 3}), "no notes fact"),
        (lambda d: d["feedback"]["wrong"].update(source={"type": "memory"}), "atlas, notes or model"),
        (lambda d: d.update(hide=["spleen"]), '"spleen" is not a structure or a group'),
        (lambda d: d["answer"]["regions"][0].update(piece="lad.0"), "not a centre-line piece"),
        (lambda d: d["feedback"]["near_misses"][0]["regions"][0].update(to=0.6), "is not a stretch of the piece"),
        (lambda d: d.pop("question"), "part.question"),
        (lambda d: d["feedback"]["near_misses"][0]["regions"][0].update({"from": 0.03}), "overlaps the correct answer"),
        (lambda d: (d["view"].update(side="anterior"), d.update(hide=[])), "of the answer can be seen from the anterior"),
    ],
)
def test_a_flawed_case_is_sent_back_with_the_reason_and_the_fix_is_accepted(spoil, reason):
    flawed = case_draft()
    spoil(flawed)
    agent, llm = agent_with(submit_click_case=[reply(call("submit_click_case", **flawed)), reply(call("submit_click_case", **case_draft()))])
    part = agent.build(Brief(request="x"), CASE_ITEM)

    assert isinstance(part, ClickCase)
    sent_back = llm.last_results("submit_click_case")[0]
    assert sent_back["is_error"] is True
    assert reason in sent_back["content"]


def test_a_hidden_answer_is_sent_back_with_what_is_in_front_of_it():
    flawed = case_draft()
    flawed["hide"] = []
    agent, llm = agent_with(submit_click_case=[reply(call("submit_click_case", **flawed)), reply(call("submit_click_case", **case_draft()))])
    agent.build(Brief(request="x"), CASE_ITEM)
    message = llm.last_results("submit_click_case")[0]["content"]
    assert "left_atrium" in message and "what_hides" in message


def test_a_part_that_keeps_failing_is_given_up_on():
    flawed = case_draft()
    flawed["hide"] = ["spleen"]
    agent, llm = agent_with(submit_click_case=[reply(call("submit_click_case", **flawed)) for _ in range(MAX_HAND_INS)])
    with pytest.raises(AgentError, match="spleen"):
        agent.build(Brief(request="x"), CASE_ITEM)
    assert len(llm.asked) == MAX_HAND_INS


def test_a_demonstration_is_built_and_one_whose_subject_is_covered_is_sent_back():
    covered = demo_draft()
    covered.update(highlight=["left_coronary_leaflet"], view={"look_at": ["left_coronary_leaflet"], "side": "superior"})
    agent, llm = agent_with(submit_demonstration=[reply(call("submit_demonstration", **covered)), reply(call("submit_demonstration", **demo_draft()))])
    part = agent.build(Brief(request="x"), DEMO_ITEM)
    assert isinstance(part, Demonstration) and part.highlight == [RCA]
    assert "of the highlighted structures can be seen from the superior" in llm.last_results("submit_demonstration")[0]["content"]


def test_a_pulse_and_a_slider_are_checked_too():
    pulse = {
        "title": "How the left coronary artery divides",
        "view": {"look_at": [LCA, LAD, CIRCUMFLEX], "side": "left"},
        "hide": ["left_atrium", "pulmonary_trunk", "cardiac_veins"],
        "from": {"piece": f"{LCA}.0", "at": 0},
        "to": None,
        "statements": [],
    }
    backwards = {**pulse, "from": {"piece": f"{LAD}.0", "at": 0.05}, "to": {"piece": f"{LCA}.0", "at": 0.01}}
    slider = {
        "title": "What a blockage cuts off",
        "view": {"look_at": [LAD], "side": "left"},
        "hide": ["left_atrium", "pulmonary_trunk", "cardiac_veins"],
        "track": {"piece": f"{LAD}.0", "from": 0, "to": 0.1145},
        "start_at": 0.08,
        "zones": [{"regions": [{"piece": f"{LAD}.0", "from": 0, "to": 0.0465}], "statement": {"text": "No branch has left yet.", "source": {"type": "model"}}}],
        "statements": [],
    }
    agent, llm = agent_with(
        submit_pulse=[reply(call("submit_pulse", **backwards)), reply(call("submit_pulse", **pulse))],
        submit_damage_slider=[reply(call("submit_damage_slider", **{**slider, "start_at": 0.5})), reply(call("submit_damage_slider", **slider))],
    )
    assert agent.build(Brief(request="x"), PlannedPart("p1", "Pulse", "pulse", "")).kind == "pulse"
    assert "pulse can't run there" in llm.last_results("submit_pulse")[0]["content"]
    assert agent.build(Brief(request="x"), PlannedPart("p2", "Slider", "damage_slider", "")).kind == "damage_slider"
    assert "outside the track" in llm.last_results("submit_damage_slider")[0]["content"]


def test_an_agent_that_only_talks_is_asked_to_hand_in_and_then_given_up_on():
    agent, llm = agent_with(submit_demonstration=[reply(says("Here is my part: ...")), reply(call("submit_demonstration", **demo_draft()))])
    assert agent.build(Brief(request="x"), DEMO_ITEM).kind == "demonstration"
    assert llm.asked[1][1][-1] == {"role": "user", "content": "Finish by calling submit_demonstration."}

    chatty, _ = agent_with(submit_demonstration=[reply(says("Thinking...")) for _ in range(40)])
    with pytest.raises(AgentError, match="ran out of turns"):
        chatty.build(Brief(request="x"), DEMO_ITEM)


def test_a_failed_lookup_is_reported_to_the_agent_not_raised():
    agent, llm = agent_with(submit_demonstration=[reply(call("branches_of", piece="aorta.9")), reply(call("submit_demonstration", **demo_draft()))])
    agent.build(Brief(request="x"), DEMO_ITEM)
    result = llm.last_results("submit_demonstration")[0]
    assert result["is_error"] is True and "not a centre-line piece" in result["content"]


# Notes


def test_notes_are_read_into_numbered_facts_with_the_page_each_rests_on():
    cited = lambda page, text: [SimpleNamespace(type="page_location", start_page_number=page, end_page_number=page, cited_text=text)]  # noqa: E731
    agent, llm = agent_with(
        notes=[
            reply(
                says("Here is what the notes say:"),
                says("The LAD is called the widow maker.", cited(3, "LAD = widow maker")),
                says("\n"),
                says("The RCA is dominant in most people.", cited(7, "Right dominance: 70%")),
            )
        ]
    )
    facts = agent.read_notes("Prepare me on coronary disease", "JVBERi0=", "lecture_07.pdf")
    assert [(f.number, f.text, f.page, f.quote) for f in facts] == [
        (1, "The LAD is called the widow maker.", 3, "LAD = widow maker"),
        (2, "The RCA is dominant in most people.", 7, "Right dominance: 70%"),
    ]
    document = llm.asked[0][1][0]["content"][0]
    assert document["type"] == "document" and document["citations"] == {"enabled": True}
    assert document["source"] == {"type": "base64", "media_type": "application/pdf", "data": "JVBERi0="}


def test_notes_with_nothing_relevant_give_no_facts():
    agent, _ = agent_with(notes=[reply(says("NONE"))])
    assert agent.read_notes("x", "JVBERi0=", "n.pdf") == []


def test_a_statement_can_rest_on_a_notes_fact_and_carries_its_file_and_page():
    draft = demo_draft()
    draft["statements"] = [{"text": "Your notes call the LAD the widow maker.", "source": {"type": "notes", "fact": 1}}]
    agent, _ = agent_with(submit_demonstration=[reply(call("submit_demonstration", **draft))])
    brief = Brief(request="x", facts=[NoteFact(1, "The LAD is called the widow maker.", "lecture_07.pdf", 3, "LAD = widow maker")])
    part = agent.build(brief, DEMO_ITEM)
    assert part.statements[0].source.model_dump() == {"type": "notes", "file": "lecture_07.pdf", "page": 3}


# Replanning and closing


def wrong_then_right():
    click = {"part_id": "p2-case", "structure_id": LAD, "point": (0, 0, 0), "piece": f"{LAD}.0", "seconds": 5.0}
    return [ClickAnswer(**click, attempt=1, at=0.08, correct=False), ClickAnswer(**click, attempt=2, at=0.02, correct=True)]


def built_case():
    agent, _ = agent_with(submit_click_case=[reply(call("submit_click_case", **case_draft()))])
    return agent.build(Brief(request="x"), CASE_ITEM)


def test_decide_can_carry_on_or_ask_for_one_extra_part():
    case = built_case()
    brief = Brief(request="x", plan=[CASE_ITEM], built=[case])
    agent, llm = agent_with(
        decide_next=[
            reply(call("decide_next", action="continue", reason="A small slip.")),
            reply(call("decide_next", action="insert", reason="They placed it too far along.")),
            reply(call("decide_next", action="insert", reason="They placed it too far along.", part={"title": "Where the septal branches leave", "kind": "demonstration", "intent": "Show the first one."})),
        ]
    )
    assert agent.decide(brief, case, wrong_then_right()) is None

    extra = agent.decide(brief, case, wrong_then_right())
    assert (extra.part_id, extra.kind) == ("extra1-where-the-septal-branches-leave", "demonstration")
    assert "They placed it too far along" in extra.intent
    task = llm.asked[0][1][0]["content"]
    assert "try 1: Anterior interventricular artery (anterior_interventricular_artery.0 at 0.0800 m); wrong" in task
    assert "try 2" in task and "correct" in task


def test_summarise_judges_from_the_clicks_and_sources_are_collected_by_code():
    case = built_case()
    brief = Brief(request="x", plan=[CASE_ITEM], built=[case])
    agent, llm = agent_with(submit_summary=[reply(call("submit_summary", solid=["Which artery supplies the septum"], shaky=["How far up a blockage must be"]))])
    assert agent.summarise(brief, wrong_then_right()) == (["Which artery supplies the septum"], ["How far up a blockage must be"])
    assert "Case: find the blockage: correct on try 2" in llm.asked[0][1][0]["content"]

    used = sources_used([case])
    assert [s.type for s in used] == ["atlas", "model", "atlas"]
    assert [getattr(s, "article", None) for s in used] == ["Left anterior descending artery", None, "Circumflex artery of heart"]


# A whole session through the requests


PLAN = {
    "can_show": ["The course of the coronary arteries"],
    "words_only": ["Which wall each artery supplies"],
    "parts": [
        {"title": "Where the right coronary artery runs", "kind": "demonstration", "intent": "Show its course."},
        {"title": "Case: find the blockage", "kind": "click_case", "intent": "Proximal blockage."},
    ],
}


@pytest.fixture
def scripted_sessions(monkeypatch):
    """Switch the session requests to the agent, with scripted replies in place of Claude."""

    def use(**replies):
        llm = Scripted(**replies)
        monkeypatch.setattr(sessions.settings, "session_source", "agent")
        monkeypatch.setattr(sessions, "make_agent", lambda usage: Agent(llm, region, articles, usage))
        return llm

    return use


def click_body(**fields):
    return {"part_id": "p2-case-find-the-blockage", "attempt": 1, "structure_id": LAD, "point": [0, 0, 0], "piece": f"{LAD}.0", "at": 0.02, "correct": True, "seconds": 4.0} | fields


def test_a_session_built_by_the_agent_runs_through_the_requests(scripted_sessions):
    extra = {"title": "Where the septal branches leave", "kind": "demonstration", "intent": "Show the first one."}
    scripted_sessions(
        submit_plan=[reply(call("submit_plan", **PLAN))],
        submit_demonstration=[reply(call("submit_demonstration", **demo_draft())), reply(call("submit_demonstration", **demo_draft("Where the septal branches leave")))],
        submit_click_case=[reply(call("submit_click_case", **case_draft()))],
        decide_next=[reply(call("decide_next", action="insert", reason="Too far along.", part=extra))],
        submit_summary=[reply(call("submit_summary", solid=["The course of the right coronary artery"], shaky=["Placing a blockage"]))],
    )
    start = client.post("/api/sessions", json={"request": "Prepare me on the blood supply of the heart"}).json()
    session_id = start["session_id"]
    assert start["scope"]["words_only"] == ["Which wall each artery supplies"]
    assert [item["kind"] for item in start["plan"]] == ["demonstration", "click_case"]

    first = client.post(f"/api/sessions/{session_id}/next").json()
    assert first["part"]["kind"] == "demonstration" and first["done"] is False
    case = client.post(f"/api/sessions/{session_id}/next").json()["part"]
    assert case["kind"] == "click_case" and case["answer"]["tolerance"] == 0.002

    client.post(f"/api/sessions/{session_id}/answers", json=click_body(attempt=1, at=0.08, correct=False))
    client.post(f"/api/sessions/{session_id}/answers", json=click_body(attempt=2))

    # The wrong click made the agent add a part, and the plan sent back shows it.
    added = client.post(f"/api/sessions/{session_id}/next").json()
    assert added["part"]["title"] == "Where the septal branches leave"
    assert [item["title"] for item in added["plan"]] == ["Where the right coronary artery runs", "Case: find the blockage", "Where the septal branches leave"]
    assert client.post(f"/api/sessions/{session_id}/next").json() == {"part": None, "plan": added["plan"], "done": True}

    summary = client.post(f"/api/sessions/{session_id}/finish").json()
    assert summary["shaky"] == ["Placing a blockage"]
    assert {source["type"] for source in summary["sources"]} == {"atlas", "model"}

    state = client.get(f"/api/sessions/{session_id}").json()
    assert (state["source"], state["parts_sent"], state["finished"], state["dropped"]) == ("agent", 3, True, [])
    assert state["claude_calls"] == 6 and state["input_tokens"] == 6000 and state["output_tokens"] == 1200


def test_a_case_answered_right_first_time_needs_no_decision(scripted_sessions):
    llm = scripted_sessions(
        submit_plan=[reply(call("submit_plan", **PLAN))],
        submit_demonstration=[reply(call("submit_demonstration", **demo_draft()))],
        submit_click_case=[reply(call("submit_click_case", **case_draft()))],
    )
    session_id = client.post("/api/sessions", json={"request": "x"}).json()["session_id"]
    client.post(f"/api/sessions/{session_id}/next")
    client.post(f"/api/sessions/{session_id}/next")
    client.post(f"/api/sessions/{session_id}/answers", json=click_body())
    assert client.post(f"/api/sessions/{session_id}/next").json()["done"] is True
    assert "decide_next" not in [stage for stage, _ in llm.asked]


def test_a_part_that_never_passes_is_left_out_and_the_session_goes_on(scripted_sessions):
    bad = demo_draft()
    bad["hide"] = ["spleen"]
    scripted_sessions(
        submit_plan=[reply(call("submit_plan", **PLAN))],
        submit_demonstration=[reply(call("submit_demonstration", **bad)) for _ in range(MAX_HAND_INS)],
        submit_click_case=[reply(call("submit_click_case", **case_draft()))],
    )
    session_id = client.post("/api/sessions", json={"request": "x"}).json()["session_id"]
    reply_ = client.post(f"/api/sessions/{session_id}/next").json()
    assert reply_["part"]["kind"] == "click_case"
    assert [item["kind"] for item in reply_["plan"]] == ["click_case"]
    dropped = client.get(f"/api/sessions/{session_id}").json()["dropped"]
    assert len(dropped) == 1 and "spleen" in dropped[0]


def test_notes_are_read_before_planning(scripted_sessions):
    cited = [SimpleNamespace(type="page_location", start_page_number=2, end_page_number=2, cited_text="LAD = widow maker")]
    llm = scripted_sessions(
        notes=[reply(says("The LAD is called the widow maker.", cited))],
        submit_plan=[reply(call("submit_plan", **PLAN))],
        submit_demonstration=[reply(call("submit_demonstration", **demo_draft()))],
    )
    response = client.post("/api/sessions", json={"request": "x", "notes": {"filename": "lecture_07.pdf", "data": "JVBERi0xLjcK"}})
    assert response.status_code == 200
    assert [stage for stage, _ in llm.asked][:2] == ["notes", "submit_plan"]
    assert "The LAD is called the widow maker. (page 2)" in llm.asked[1][1][0]["content"]


def test_a_failure_of_claude_at_the_start_is_reported_in_words(scripted_sessions):
    scripted_sessions(submit_plan=[LLMError("The Anthropic API key was not accepted. Check ANTHROPIC_API_KEY in .env.")])
    response = client.post("/api/sessions", json={"request": "x"})
    assert response.status_code == 502
    assert response.json()["detail"] == "The tutor could not do that: The Anthropic API key was not accepted. Check ANTHROPIC_API_KEY in .env."


def test_the_app_can_ask_where_sessions_come_from(monkeypatch):
    assert client.get("/api/tutor").json() == {"source": "sample"}
    monkeypatch.setattr(sessions.settings, "session_source", "agent")
    assert client.get("/api/tutor").json() == {"source": "agent"}


def test_the_sample_is_the_default_and_makes_no_calls():
    start = client.post("/api/sessions", json={"request": "x"}).json()
    state = client.get(f"/api/sessions/{start['session_id']}").json()
    assert (state["source"], state["claude_calls"]) == ("sample", 0)
