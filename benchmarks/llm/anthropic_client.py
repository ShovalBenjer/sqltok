"""Anthropic provider. Reads the API key from ``ANTHROPIC_API_KEY``."""

from __future__ import annotations

import os

from .base import LLMClient, LLMResponse


class AnthropicClient(LLMClient):
    """Calls the Anthropic Messages API.

    Pricing defaults are placeholders; override with ``--in-price/--out-price``
    on the CLI for accurate cost estimates.
    """

    input_price_per_m = 3.0
    output_price_per_m = 15.0

    def __init__(self, model: str, *, cache=None, max_tokens: int = 512) -> None:  # noqa: ANN001
        super().__init__(model, cache=cache)
        self.max_tokens = max_tokens
        self._client = None

    @property
    def provider(self) -> str:
        return "anthropic"

    def _ensure_client(self) -> None:
        if self._client is None:
            import anthropic  # imported lazily so core install stays light

            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise RuntimeError("ANTHROPIC_API_KEY is not set")
            self._client = anthropic.Anthropic(api_key=api_key)

    def _complete(self, system: str, prompt: str) -> LLMResponse:
        self._ensure_client()
        assert self._client is not None
        message = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            block.text for block in message.content if getattr(block, "type", None) == "text"
        )
        return LLMResponse(
            text=text,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            model=self.model,
        )
