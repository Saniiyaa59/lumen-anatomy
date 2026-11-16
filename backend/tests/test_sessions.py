import base64
import copy
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.session_schemas import ClickAnswer, RecordedSession
from app.sessions import MAX_NOTES_BYTES, SAMPLE_PATH, load_sample

client = TestClient(app)

SAMPLE = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
PDF = base64.b64encode(b"%PDF-1.7\n% a very small stand-in for lecture notes\n").decode()
LAD = "anterior_interventricular_artery"


def start(**body):
    return client.post("/api/sessions", json={"request": "Prepare me on the blood supply of the heart"} | body)


def click(part_id="case-septum", **fields):
    return {
        "part_id": part_id,
        "attempt": 1,
        "structure_id": LAD,
        "point": [0.05, 1.29, 0.06],
        "piece": f"{LAD}.0",
        "at": 0.02,
        "correct": True,
        "seconds": 8.5,
    } | fields


def broken(change):
    """A copy of the sample with one change made to it."""
    session = copy.deepcopy(SAMPLE)
    change(session)
    return session


# The sample and the models


def test_sample_fits_the_models_and_comes_back_unchanged():
    """The frontend checks the same file, so this keeps the two sides in step."""
    assert load_sample().model_dump(mode="json", by_alias=True) == SAMPLE


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda s: s.update(format="lumen.session/9"), "lumen.session/0.1"),
        (lambda s: s["parts"][0]["statements"][0].pop("source"), "source"),
        (lambda s: s["parts"][0]["statements"][0].update(source={"type": "memory"}), "notes"),
        (lambda s: s["parts"][0]["statements"][0].update(source={"type": "notes", "file": "a.pdf", "page": 0}), "page"),
        (lambda s: s["parts"][0].update(statements=[]), "statements"),
        (lambda s: s["parts"][0].update(kind="quiz"), "kind"),
        (lambda s: s["parts"][0]["view"].update(side="front"), "side"),
        (lambda s: s["parts"][2].update(start_at=0.2), "outside the track"),
        (lambda s: s["parts"][3]["answer"]["regions"][0].update({"from": 0.04, "to": 0.01}), "must be less than"),
        (lambda s: s["parts"][3]["answer"].update(regions=[]), "at least one stretch"),
        (lambda s: s["parts"][3]["feedback"]["near_misses"][1]["regions"][0].update({"from": 0.03}), "overlaps the correct answer"),
        (lambda s: s["plan"][0].update(part_id="intro"), "not the id of a part"),
        (lambda s: s["plan"][0].update(kind="pulse"), "but the part is"),
        (lambda s: s["parts"][1].update(id="origins"), "more than one part"),
        (lambda s: s["parts"][0].update(colour="red"), "colour"),
    ],
)
def test_models_reject_a_session_that_does_not_fit(change, message):
    with pytest.raises(ValidationError, match=message):
        RecordedSession.model_validate(broken(change))


def test_an_answer_needs_a_whole_place_or_none():
    assert ClickAnswer.model_validate(click(piece=None, at=None)).piece is None
    with pytest.raises(ValidationError, match="both be given or both be null"):
        ClickAnswer.model_validate(click(at=None))


# Starting


def test_start_returns_the_plan_without_any_parts():
    response = start()
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"format", "session_id", "region", "request", "scope", "plan"}
    assert body["format"] == "lumen.session/0.1"
    assert [item["part_id"] for item in body["plan"]] == [part["id"] for part in SAMPLE["parts"]]


def test_start_echoes_what_the_student_asked_and_gives_each_session_its_own_id():
    first = start(request="  Prepare me on coronary dominance  ").json()
    second = start().json()
    assert first["request"] == "Prepare me on coronary dominance"
    assert first["session_id"] != second["session_id"]


def test_an_empty_request_opens_the_model_to_explore():
    for body in ({"request": ""}, {}):
        opened = client.post("/api/sessions", json=body).json()
        assert opened["plan"] == [] and opened["request"] == "Explore the heart" and "answer" not in opened
        session_id = opened["session_id"]
        assert client.post(f"/api/sessions/{session_id}/next").json() == {"part": None, "plan": [], "done": True}
        # With the tutor switched off there is nobody to answer.
        assert client.post(f"/api/sessions/{session_id}/chat", json={"text": "what is this?"}).status_code == 409


def test_start_keeps_uploaded_notes():
    session_id = start(notes={"filename": "lecture_07.pdf", "data": PDF}).json()["session_id"]
    state = client.get(f"/api/sessions/{session_id}").json()
    assert state["notes"] == "lecture_07.pdf"
    assert state["notes_bytes"] == len(base64.b64decode(PDF))


def test_start_rejects_notes_that_are_not_a_pdf():
    not_pdf = base64.b64encode(b"just some text").decode()
    response = start(notes={"filename": "notes.txt", "data": not_pdf})
    assert response.status_code == 422
    assert "PDF" in response.json()["detail"]
    assert start(notes={"filename": "notes.pdf", "data": "not base64!"}).status_code == 422


def test_start_rejects_notes_that_are_too_large():
    too_big = base64.b64encode(b"%PDF" + b"0" * MAX_NOTES_BYTES).decode()
    assert start(notes={"filename": "huge.pdf", "data": too_big}).status_code == 413


# Stepping through


def test_parts_arrive_one_at_a_time_in_plan_order_then_done():
    session_id = start().json()["session_id"]
    received = []
    for _ in SAMPLE["parts"]:
        reply = client.post(f"/api/sessions/{session_id}/next").json()
        assert reply["done"] is False
        received.append(reply["part"])
    assert received == SAMPLE["parts"]

    after = client.post(f"/api/sessions/{session_id}/next").json()
    assert after == {"part": None, "plan": SAMPLE["plan"], "done": True}


def test_two_sessions_keep_their_own_place():
    first = start().json()["session_id"]
    second = start().json()["session_id"]
    client.post(f"/api/sessions/{first}/next")
    client.post(f"/api/sessions/{first}/next")
    assert client.post(f"/api/sessions/{second}/next").json()["part"]["id"] == SAMPLE["parts"][0]["id"]


def test_finish_returns_the_summary():
    session_id = start().json()["session_id"]
    assert client.post(f"/api/sessions/{session_id}/finish").json() == SAMPLE["summary"]
    assert client.get(f"/api/sessions/{session_id}").json()["finished"] is True


# Answers


def reach_the_case():
    session_id = start().json()["session_id"]
    for _ in SAMPLE["parts"]:
        client.post(f"/api/sessions/{session_id}/next")
    return session_id


def test_answers_are_recorded_in_order():
    session_id = reach_the_case()
    wrong = click(attempt=1, at=0.08, correct=False)
    right = click(attempt=2, at=0.02, correct=True)
    assert client.post(f"/api/sessions/{session_id}/answers", json=wrong).json() == {"plan": SAMPLE["plan"]}
    assert client.post(f"/api/sessions/{session_id}/answers", json=right).status_code == 200
    assert client.get(f"/api/sessions/{session_id}").json()["answers"] == [wrong, right]


def test_an_answer_to_a_click_off_any_vessel_is_recorded():
    session_id = reach_the_case()
    answer = click(structure_id="left_ventricle", piece=None, at=None, correct=False)
    assert client.post(f"/api/sessions/{session_id}/answers", json=answer).status_code == 200


def test_an_answer_must_be_for_a_case_that_has_been_sent():
    session_id = start().json()["session_id"]
    not_sent_yet = client.post(f"/api/sessions/{session_id}/answers", json=click())
    assert not_sent_yet.status_code == 422
    assert "not a case" in not_sent_yet.json()["detail"]

    client.post(f"/api/sessions/{session_id}/next")
    not_a_case = client.post(f"/api/sessions/{session_id}/answers", json=click(part_id="origins"))
    assert not_a_case.status_code == 422


def test_a_malformed_answer_is_rejected():
    session_id = reach_the_case()
    assert client.post(f"/api/sessions/{session_id}/answers", json=click(attempt=0)).status_code == 422
    assert client.post(f"/api/sessions/{session_id}/answers", json=click(at=None)).status_code == 422


# Unknown sessions


@pytest.mark.parametrize(
    ("method", "path"),
    [("post", "/next"), ("post", "/finish"), ("get", "")],
)
def test_an_unknown_session_is_not_found(method, path):
    response = getattr(client, method)(f"/api/sessions/no-such-session{path}")
    assert response.status_code == 404
    assert "restarted" in response.json()["detail"]


def test_an_answer_for_an_unknown_session_is_not_found():
    assert client.post("/api/sessions/no-such-session/answers", json=click()).status_code == 404
