"""What the tutor is doing, for the student to read while they wait."""

from app import sessions
from app.agent import Brief
from app.progress import Progress, describe_lookup, page_title
from test_agent import (  # the scripted stand-in for Claude, and its fixture
    DEMO_ITEM,
    LAD,
    PLAN,
    agent_with,
    articles,
    call,
    case_draft,
    client,
    demo_draft,
    region,
    reply,
    scripted_sessions,  # noqa: F401  (a fixture, used by name)
)


def test_each_lookup_reads_as_a_step_a_student_understands():
    assert describe_lookup("describe", {"id": "right_coronary_artery"}, region, articles) == "Looking at the right coronary artery"
    assert describe_lookup("branches_of", {"piece": f"{LAD}.0"}, region, articles) == "Finding the branches of the anterior interventricular artery"
    assert describe_lookup("beyond", {"piece": f"{LAD}.0", "at": 0.02}, region, articles).startswith("Working out what a blockage on the anterior")
    assert describe_lookup("search_notes", {"query": "widow maker"}, region, articles) == "Searching your notes for “widow maker”"
    assert describe_lookup("read_article", {"article": "Left ventricle"}, region, articles) == "Reading the atlas page on Ventricle (heart)"
    assert describe_lookup("branches_of", {"piece": "nonsense.0"}, region, articles) == "Looking something up"


def test_a_page_title_comes_from_its_link():
    assert page_title("https://en.wikipedia.org/wiki/Atrium_(heart)#Structure") == "Atrium (heart)"
    assert page_title(None) is None and page_title("https://example.org/x") is None


def test_stages_run_side_by_side_and_end():
    progress = Progress()
    progress.begin("part a", "Building “A”")
    progress.begin("part b", "Building “B”")
    progress.step("part b", "Choosing a view")
    progress.step("gone", "ignored")
    assert [(w.stage, w.detail) for w in progress.working()] == [("part a", None), ("part b", "Choosing a view")]
    progress.end("part a")
    assert [w.stage for w in progress.working()] == ["part b"]


def test_while_a_part_is_built_its_stage_and_latest_step_show_and_then_clear():
    agent, llm = agent_with(submit_demonstration=[reply(call("describe", id="right_coronary_artery")), reply(call("submit_demonstration", **demo_draft()))])
    seen = []
    ask = llm.ask

    def watching(**request):
        seen.append([(w.doing, w.detail) for w in agent.progress.working()])
        return ask(**request)

    llm.ask = watching
    agent.build(Brief(request="x"), DEMO_ITEM)
    assert seen == [
        [("Building “Where the right coronary artery runs”", None)],
        [("Building “Where the right coronary artery runs”", "Looking at the right coronary artery")],
    ]
    assert agent.progress.working() == []


def test_the_browser_can_ask_by_its_own_key_while_a_session_starts_and_by_session_id_after(scripted_sessions):
    llm = scripted_sessions(submit_plan=[reply(call("submit_plan", **PLAN))], submit_demonstration=[reply(call("submit_demonstration", **demo_draft()))], submit_click_case=[reply(call("submit_click_case", **case_draft()))])
    seen = []
    ask = llm.ask

    def watching(**request):
        if request["tools"][-1]["name"] == "submit_plan":
            seen.append([w.doing for w in sessions._progress["browser-key-1"].working()])
        return ask(**request)

    llm.ask = watching
    session_id = client.post("/api/sessions", json={"request": "coronary arteries", "progress_key": "browser-key-1"}).json()["session_id"]
    assert seen == [["Planning your session"]]
    assert "browser-key-1" not in sessions._progress  # forgotten once the session has started
    for future in list(sessions._sessions[session_id].tutor.building.values()):
        future.exception()
    assert client.get(f"/api/sessions/progress/{session_id}").json() == {"working": []}
    assert client.get("/api/sessions/progress/no-such-key").json() == {"working": []}
