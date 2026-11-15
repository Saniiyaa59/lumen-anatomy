"""The one place the backend talks to Claude.

Everything else asks through `LLM.ask`, so tests can pass a stand-in that
replays scripted replies and no test ever spends money or needs a key.
"""

from dataclasses import dataclass
from typing import Any, Protocol

import anthropic

from app.config import settings

DEFAULT_MODEL = "claude-opus-5-5"
MAX_TOKENS = 16000
# Lets the API hand a request it declines for safety reasons to another model
# instead of failing; a tutor on anatomy should rarely need it.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(Exception):
    """A request to Claude failed. The message is fit to show the student."""


@dataclass
class Usage:
    """Running totals for one session, so its cost can be seen."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def add(self, usage: Any) -> None:
        self.calls += 1
        self.input_tokens += getattr(usage, "input_tokens", 0) or 0
        self.output_tokens += getattr(usage, "output_tokens", 0) or 0
        self.cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
        self.cache_write_tokens += getattr(usage, "cache_creation_input_tokens", 0) or 0


class LLM(Protocol):
    def ask(self, *, system: str, messages: list[dict], tools: list[dict] | None = None) -> Any:
        """One request. Returns the SDK's message: `.content` blocks, `.stop_reason`, `.usage`."""
        ...


class ClaudeLLM:
    """Claude through the Anthropic SDK."""

    def __init__(self, model: str | None = None, effort: str | None = None, api_key: str | None = None):
        self.model = model or settings.llm_model or DEFAULT_MODEL
        self.effort = effort or settings.llm_effort or "high"
        # The key lives in the repo's .env, which is read into settings but not into
        # the process environment, so it is handed over here. With none, the SDK
        # falls back to its own lookup (environment, then an `ant auth login` profile).
        key = api_key or settings.anthropic_api_key
        self.client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()

    def ask(self, *, system: str, messages: list[dict], tools: list[dict] | None = None) -> Any:
        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            # The instructions are the same for every call of a session, so they are cached.
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": messages,
            # Work on one part takes many turns, each resending the conversation so far. This
            # caches everything up to the latest turn, so only what is new is paid for in full.
            "cache_control": {"type": "ephemeral"},
            "output_config": {"effort": self.effort},
            "betas": [FALLBACK_BETA],
            "fallbacks": "default",
        }
        if tools:
            request["tools"] = tools
        try:
            response = self.client.beta.messages.create(**request)
        except anthropic.AuthenticationError:
            raise LLMError("The Anthropic API key was not accepted. Check ANTHROPIC_API_KEY in .env.") from None
        except anthropic.RateLimitError:
            raise LLMError("The Claude API is rate-limiting this key, or its credit has run out. Try again shortly.") from None
        except anthropic.APIStatusError as error:
            raise LLMError(f"The Claude API refused the request ({error.status_code}): {error.message}") from None
        except anthropic.APIConnectionError:
            raise LLMError("The Claude API could not be reached. Check the internet connection.") from None
        if response.stop_reason == "refusal":
            raise LLMError("Claude declined this request.")
        if response.stop_reason == "max_tokens":
            raise LLMError("Claude ran out of room before finishing its reply.")
        return response
