"""Placeholder for the agent: returns sample responses from assets/fixtures/.

Lets the frontend call the real endpoint before the agent exists. Replaced by
the agent loop in Phase 4; the sample files stay as frontend mock data.
"""

from functools import lru_cache

from app.config import REPO_ROOT
from app.schemas import CommandRequest, CommandResponse

FIXTURES_DIR = REPO_ROOT / "assets" / "fixtures"


@lru_cache
def load_fixture(name: str) -> CommandResponse:
    """Load and validate one sample response, so samples can't drift from the schema."""
    return CommandResponse.model_validate_json((FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))


def stub_response(request: CommandRequest) -> CommandResponse:
    if not request.selection:
        return load_fixture("clarification")
    if request.toolbar_command == "compare":
        return load_fixture("compare_valves")
    return load_fixture("here_to_there")
