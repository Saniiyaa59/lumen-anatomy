"""Settings loaded from the repo-root .env file (see .env.example)."""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    frontend_origin: str = "http://localhost:5173"
    registry_path: Path = REPO_ROOT / "assets" / "structures.json"

    # Where a study session's parts come from. "sample" is free; "agent" calls Claude and costs money per session.
    session_source: Literal["sample", "agent"] = "sample"
    anthropic_api_key: str | None = None
    llm_model: str = ""  # empty means the default in app/llm.py
    llm_effort: str = ""  # low, medium, high, xhigh or max; empty means high

    # Where study sessions are saved, so they survive a restart, and how many days an untouched one is kept.
    sessions_db: Path = REPO_ROOT / "data" / "lumen.db"
    session_days: float = 30


settings = Settings()
