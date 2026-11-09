"""Settings loaded from the repo-root .env file (see .env.example)."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    frontend_origin: str = "http://localhost:5173"
    registry_path: Path = REPO_ROOT / "assets" / "structures.json"


settings = Settings()
