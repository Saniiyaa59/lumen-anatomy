"""Guards for every backend test.

The tests must never call the Claude API: it costs money and needs a key. Whether
sessions use the agent is a line in the developer's own .env, so without these
guards a test run on a machine with SESSION_SOURCE=agent would start real
sessions. That happened once, on 2026-11-14.
"""

import pytest

from app import sessions, store
from app.llm import ClaudeLLM


@pytest.fixture(autouse=True)
def never_call_claude(monkeypatch):
    """Whatever .env says: sessions come from the sample, and any real request to Claude fails the test."""
    monkeypatch.setattr(sessions.settings, "session_source", "sample")

    def refuse(*args, **kwargs):
        raise AssertionError("A test tried to call the Claude API. Pass scripted replies instead (see tests/test_agent.py).")

    monkeypatch.setattr(ClaudeLLM, "ask", refuse)
    monkeypatch.setattr(sessions, "make_agent", refuse)


@pytest.fixture(autouse=True)
def fresh_session_store(monkeypatch, tmp_path):
    """Each test saves sessions to its own empty database, never the developer's data/lumen.db, and starts with none in memory."""
    monkeypatch.setattr(sessions.settings, "sessions_db", tmp_path / "lumen.db")
    monkeypatch.setattr(sessions.settings, "session_days", 30)
    store.get_store.cache_clear()
    sessions._sessions.clear()
    yield
    store.get_store.cache_clear()
    sessions._sessions.clear()
