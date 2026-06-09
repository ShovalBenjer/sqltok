"""OpenAI provider. Reads the API key from ``OPENAI_API_KEY``."""

from __future__ import annotations

import os

from .base import LLMClient, LLMResponse


class OpenAIClient(LLMClient):
    """Calls the OpenAI Chat Completions API.

    Pricing defaults are placeholders; override with ``--in-price/--out-price``
    on the CLI for accurate cost estimates.
    """

    input_price_per_m = 0.5
    output_price_per_m = 1.5

    def __init__(self, model: str, *, cache=None, max_tokens: int = 512) -> None:  # noqa: ANN001
        super().__init__(model, cache=cache)
        self.max_tokens = max_tokens
        self._client = None

    @property
    def provider(self) -> str:
        return "openai"

    def _ensure_client(self) -> None:
        if self._client is None:
            import openai  # imported lazily so core install stays light

            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError("OPENAI_API_KEY is not set")
            self._client = openai.OpenAI(api_key=api_key)

    def _complete(self, system: str, prompt: str) -> LLMResponse:
        self._ensure_client()
        assert self._client is not None
        completion = self._client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        text = completion.choices[0].message.content or ""
        usage = completion.usage
        return LLMResponse(
            text=text,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            model=self.model,
        )
