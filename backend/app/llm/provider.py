"""LLM providers. The app talks only to LLMProvider; Anthropic is the first implementation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol


class LLMUnavailable(Exception):
    """The LLM feature can't run (no key, privacy toggle off, cap reached, provider error)."""


# Fixed text for Settings › Test connection: no portfolio data, no system prompt.
PING_PROMPT = "Connection test. Reply with the single word: ok"
PING_MAX_TOKENS = 16


def provider_error_text(e: Exception) -> str:
    """The provider's own error type and message (never headers or the key)."""
    import anthropic as a

    if isinstance(e, a.APIStatusError):
        err = (e.body or {}).get("error", {}) if isinstance(e.body, dict) else {}
        etype, msg = err.get("type"), err.get("message")
        return f"Anthropic API error {e.status_code}" + (f" ({etype})" if etype else "") + (f": {msg}" if msg else "")
    if isinstance(e, a.APIConnectionError):
        return f"Could not reach the Anthropic API ({type(e).__name__}: {e})"
    return f"{type(e).__name__}: {e}"


@dataclass(frozen=True)
class Ping:
    model: str
    stop_reason: str | None
    text: str
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class Completion:
    text: str
    model: str  # model that actually served the request (fallbacks may change it)
    input_tokens: int
    output_tokens: int


class LLMProvider(Protocol):
    name: str
    model: str

    def complete_json(self, system: str, messages: list[dict], schema: dict, max_tokens: int = 16000) -> Completion: ...


class AnthropicProvider:
    """Anthropic Messages API with structured outputs and server-side refusal fallbacks."""

    name = "anthropic"

    def __init__(self, model: str = "claude-opus-5-5", effort: str = "high", api_key: str | None = None,
                 refusal_fallback: bool = False):
        import anthropic

        from app.config import get_settings

        key = api_key or get_settings().anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise LLMUnavailable("No ANTHROPIC_API_KEY set (add it to .env); AI analysis is disabled.")
        self.model, self.effort, self.refusal_fallback = model, effort, refusal_fallback
        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=key, timeout=120.0, max_retries=2)

    def _create(self, **params):
        a = self._anthropic
        try:
            if self.refusal_fallback:  # opt-in (Settings); default off
                return self._client.beta.messages.create(**params, betas=["server-side-fallback-2026-07-01"],
                                                         fallbacks="default")
            return self._client.messages.create(**params)
        except (a.APIStatusError, a.APIConnectionError) as e:
            raise LLMUnavailable(provider_error_text(e)) from None

    def ping(self) -> Ping:
        """Minimal request (Settings › Test connection): fixed prompt, tiny max_tokens, no personal data."""
        resp = self._create(model=self.model, max_tokens=PING_MAX_TOKENS,
                            messages=[{"role": "user", "content": PING_PROMPT}])
        text = next((b.text for b in resp.content if b.type == "text"), "")
        return Ping(resp.model, resp.stop_reason, text, resp.usage.input_tokens, resp.usage.output_tokens)

    def complete_json(self, system: str, messages: list[dict], schema: dict, max_tokens: int = 16000) -> Completion:
        params = dict(model=self.model, max_tokens=max_tokens, system=system, messages=messages,
                      output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}})
        resp = self._create(**params)
        if resp.stop_reason == "refusal":
            raise LLMUnavailable("The model declined this request.")
        if resp.stop_reason == "max_tokens":
            raise LLMUnavailable("The response was cut off (max_tokens).")
        text = next((b.text for b in resp.content if b.type == "text"), "")
        return Completion(text, resp.model, resp.usage.input_tokens, resp.usage.output_tokens)


class StubProvider:
    """Other providers are not implemented yet; tests inject their own fake with the same interface."""

    name = "stub"

    def __init__(self, model: str = "stub"):
        self.model = model

    def complete_json(self, system, messages, schema, max_tokens=16000) -> Completion:
        raise LLMUnavailable("No LLM provider is configured.")
