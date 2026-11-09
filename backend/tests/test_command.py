import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.stub import FIXTURES_DIR, load_fixture

client = TestClient(app)


def command(**fields):
    body = {"session_id": "test", "input_type": "text", "text": "How does blood get from here to there?"}
    return client.post("/api/command", json=body | fields)


def test_selection_returns_actions_and_citations():
    response = command(
        selection=["right_atrium", "aorta"],
        click_events=[{"t": 41.2, "structure_id": "right_atrium"}, {"t": 42.0, "structure_id": "aorta"}],
    )
    assert response.status_code == 200
    body = response.json()
    assert body["clarification"] is None
    assert body["citations"][0]["chunk_id"]
    assert {"type": "animate_path", "path": "blood_flow", "from": "right_atrium", "to": "aorta"} in body["actions"]


def test_compare_button_highlights_in_two_colors():
    body = command(text=None, toolbar_command="compare", selection=["mitral_valve", "aortic_valve"]).json()
    colors = [a["color"] for a in body["actions"] if a["type"] == "highlight"]
    assert colors == ["primary", "secondary"]


def test_no_selection_asks_for_a_click():
    body = command(text="Why is this wall so thick?").json()
    assert body["clarification"] == "Click the structure you mean."
    assert body["actions"] == []


@pytest.mark.parametrize(
    "fields",
    [
        {"selection": ["spleen"]},
        {"click_events": [{"t": 1.0, "structure_id": "spleen"}]},
        {"input_type": "voice"},  # no audio
        {"text": None},  # no text and no toolbar command
        {"mode": "sleep"},
    ],
    ids=["unknown-selection", "unknown-click", "voice-without-audio", "empty-text", "bad-mode"],
)
def test_bad_requests_are_rejected(fields):
    assert command(**fields).status_code == 422


@pytest.mark.parametrize("path", sorted(FIXTURES_DIR.glob("*.json")), ids=lambda p: p.stem)
def test_every_fixture_matches_the_schema(path):
    load_fixture(path.stem)
