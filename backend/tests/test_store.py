"""Sessions are saved after each request and survive a restart.

A restart is imitated by emptying the sessions held in memory, so the next
request has to load the session from the store.
"""

import base64
import time

from app import sessions
from app.store import SessionStore
from test_agent import (  # the scripted stand-in for Claude, and its fixture
    PLAN,
    RCA,
    answer,
    ask,
    call,
    case_draft,
    client,
    demo_draft,
    reply,
    says,
    scripted_sessions,  # noqa: F401  (a fixture, used by name)
)

PDF = base64.b64encode(b"%PDF-1.7\n% stand-in notes\n").decode()


def restart():
    sessions._sessions.clear()


def test_a_sample_session_carries_on_after_a_restart():
    session_id = client.post("/api/sessions", json={"request": "Prepare me"}).json()["session_id"]
    first = client.post(f"/api/sessions/{session_id}/next").json()["part"]
    restart()
    second = client.post(f"/api/sessions/{session_id}/next").json()["part"]
    assert second["id"] != first["id"]
    assert client.get(f"/api/sessions/{session_id}").json()["parts_sent"] == 2


def test_an_agent_session_carries_on_after_a_restart_with_its_plan_parts_answers_and_conversation(scripted_sessions):
    llm = scripted_sessions(
        notes=[reply(says("NONE"))],
        submit_plan=[reply(call("submit_plan", **PLAN))],
        submit_demonstration=[reply(call("submit_demonstration", **demo_draft()))],
        # Built once ahead of the student before the restart, and again after it, since a part being built is not saved.
        submit_click_case=[reply(call("submit_click_case", **case_draft())), reply(call("submit_click_case", **case_draft()))],
        answer_student=[answer()],
        submit_summary=[reply(call("submit_summary", solid=["The right coronary artery"], shaky=["Placing a blockage"]))],
    )
    start = client.post("/api/sessions", json={"request": "coronary arteries", "notes": {"filename": "lecture.pdf", "data": PDF}}).json()
    session_id = start["session_id"]
    first = client.post(f"/api/sessions/{session_id}/next").json()["part"]
    client.post(f"/api/sessions/{session_id}/chat", json={"text": "where does it run?", "selected": [RCA]})
    for future in list(sessions._sessions[session_id].tutor.building.values()):
        future.exception()  # let the part being built ahead finish, so nothing changes while comparing
    before = client.get(f"/api/sessions/{session_id}").json()

    # Each request to Claude so far was timed, under the task it belonged to.
    assert {"notes", "plan", "chat"} <= {t["stage"] for t in before["timings"]}
    assert any(t["stage"].startswith("part ") for t in before["timings"])
    assert len(before["timings"]) == before["claude_calls"]

    restart()
    after = client.get(f"/api/sessions/{session_id}").json()
    # A builder running ahead may record its last request after the session was saved.
    saved_timings = after.pop("timings")
    assert saved_timings == before.pop("timings")[: len(saved_timings)]
    assert after == before
    assert after["notes"] == "lecture.pdf" and after["notes_bytes"] > 0

    case = client.post(f"/api/sessions/{session_id}/next").json()
    assert case["part"]["kind"] == "click_case"
    assert [i["part_id"] for i in case["plan"]] == [i["part_id"] for i in start["plan"]]
    client.post(
        f"/api/sessions/{session_id}/answers",
        json={"part_id": case["part"]["id"], "attempt": 1, "structure_id": RCA, "point": [0, 0, 0], "piece": None, "at": None, "correct": True, "seconds": 3.0},
    )

    restart()
    summary = client.post(f"/api/sessions/{session_id}/finish").json()
    assert summary["solid"] == ["The right coronary artery"]
    # The conversation from before the restart reached the agent afterwards.
    assert "The student said: where does it run?" in [m for s, m in llm.asked if s == "submit_summary"][0][0]["content"]

    restart()
    # A finished session's summary is kept: asking again costs nothing.
    assert client.post(f"/api/sessions/{session_id}/finish").json() == summary
    state = client.get(f"/api/sessions/{session_id}").json()
    assert state["finished"] is True and len(state["answers"]) == 1
    assert first["kind"] == "demonstration"


def test_a_question_waiting_for_an_answer_survives_a_restart(scripted_sessions):
    scripted_sessions(submit_plan=[ask(), reply(call("submit_plan", **PLAN))], submit_demonstration=[reply(call("submit_demonstration", **demo_draft()))])
    session_id = client.post("/api/sessions", json={"request": "exam"}).json()["session_id"]
    restart()
    assert client.post(f"/api/sessions/{session_id}/next").status_code == 409
    planned = client.post(f"/api/sessions/{session_id}/reply", json={"text": "Coronary arteries"}).json()
    assert [i["kind"] for i in planned["plan"]] == ["demonstration", "click_case"]


def test_the_pdf_itself_is_not_kept():
    session_id = client.post("/api/sessions", json={"request": "x", "notes": {"filename": "a.pdf", "data": PDF}}).json()["session_id"]
    saved = sessions.get_store().load(session_id)
    assert saved["notes_bytes"] > 0 and PDF not in str(saved)
    assert not hasattr(sessions._sessions[session_id], "notes")


def test_a_session_saved_by_an_older_version_is_refused_in_words():
    session_id = client.post("/api/sessions", json={"request": "x"}).json()["session_id"]
    store = sessions.get_store()
    store.save(session_id, store.load(session_id) | {"version": 0})
    restart()
    refused = client.post(f"/api/sessions/{session_id}/next")
    assert refused.status_code == 410 and "older version" in refused.json()["detail"]


def test_old_sessions_are_cleared(tmp_path, monkeypatch):
    store = SessionStore(tmp_path / "old.db")
    store.save("old", {"x": 1})
    store.save("new", {"x": 2})
    monkeypatch.setattr(time, "time", lambda: 1e12)  # far in the future: both are old by now
    assert store.forget_older_than(30) == 2
    assert store.load("old") is None
