"""Where study sessions are kept between requests and across restarts.

One SQLite file (data/lumen.db by default) with one row per session: its id,
when it last changed, and everything about it as JSON. sessions.py decides what
goes in the JSON; this module only reads and writes rows.

Look inside with:

    sqlite3 data/lumen.db "select id, datetime(updated, 'unixepoch'), length(data) from sessions"
"""

import json
import sqlite3
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import REPO_ROOT, settings


class SessionStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("create table if not exists sessions (id text primary key, updated real not null, data text not null)")

    def _connect(self) -> sqlite3.Connection:
        # A connection per call: requests and part builders run on different threads.
        return sqlite3.connect(self.path, timeout=10)

    def save(self, session_id: str, data: dict[str, Any]) -> None:
        with self._connect() as db:
            db.execute(
                "insert into sessions (id, updated, data) values (?, ?, ?) on conflict(id) do update set updated = excluded.updated, data = excluded.data",
                (session_id, time.time(), json.dumps(data)),
            )

    def load(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("select data from sessions where id = ?", (session_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def forget_older_than(self, days: float) -> int:
        """Delete sessions untouched for this many days. Returns how many were deleted."""
        with self._connect() as db:
            return db.execute("delete from sessions where updated < ?", (time.time() - days * 86400,)).rowcount


@lru_cache
def get_store() -> SessionStore:
    """The store, opened once. Sessions left alone longer than SESSION_DAYS are cleared when it opens."""
    path = settings.sessions_db
    store = SessionStore(path if path.is_absolute() else REPO_ROOT / path)
    store.forget_older_than(settings.session_days)
    return store
