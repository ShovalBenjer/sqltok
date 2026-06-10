"""A deterministic mock LLM that emits canned SQL (no API keys needed).

Used to verify the harness end-to-end -- prompt construction, caching, output
files -- without spending money or hitting the network. It does not attempt to
answer questions correctly; execution accuracy with the mock is meaningless by
design.
"""

from __future__ import annotations

import tiktoken

from .base import LLMClient, LLMResponse

_CANNED_SQL = "SELECT 1;"


class MockLLMClient(LLMClient):
    """Echoes a fixed SQL string, with real tiktoken token accounting."""

    def __init__(self, model: str = "mock-1", *, cache=None) -> None:  # noqa: ANN001
        super().__init__(model, cache=cache)
        self._enc = tiktoken.get_encoding("cl100k_base")

    @property
    def provider(self) -> str:
        return "mock"

    def _complete(self, system: str, prompt: str) -> LLMResponse:
        text = _CANNED_SQL
        return LLMResponse(
            text=text,
            input_tokens=len(self._enc.encode(system + "\n" + prompt)),
            output_tokens=len(self._enc.encode(text)),
            model=self.model,
        )
