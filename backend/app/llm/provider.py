"""LLM providers. The app talks only to LLMProvider; Anthropic is the first implementation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol


class LLMUnavailable(Exception):
    """The LLM feature can't run (no key, privacy toggle off, cap reached, provider error)."""


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

    def complete_json(self, system: str, messages: list[dict], schema: dict, max_tokens: int = 16000) -> Completion:
        a = self._anthropic
        params = dict(model=self.model, max_tokens=max_tokens, system=system, messages=messages,
                      output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}})
        try:
            if self.refusal_fallback:  # opt-in (Settings); default off
                resp = self._client.beta.messages.create(**params, betas=["server-side-fallback-2026-07-01"],
                                                         fallbacks="default")
            else:
                resp = self._client.messages.create(**params)
        except a.AuthenticationError:
            raise LLMUnavailable("The Anthropic API key was rejected.") from None
        except a.RateLimitError:
            raise LLMUnavailable("Rate limited by the Anthropic API; try again later.") from None
        except a.APIStatusError as e:
            raise LLMUnavailable(f"Anthropic API error {e.status_code}.") from None
        except a.APIConnectionError:
            raise LLMUnavailable("Could not reach the Anthropic API (network).") from None
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
