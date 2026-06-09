"""Provider-agnostic LLM clients for the benchmark harness."""

from __future__ import annotations

from .base import DiskCache, LLMClient, LLMResponse
from .mock import MockLLMClient


def build_client(provider: str, model: str, *, cache: DiskCache | None = None) -> LLMClient:
    """Construct an :class:`LLMClient` for a provider name."""
    if provider == "mock":
        return MockLLMClient(model, cache=cache)
    if provider == "anthropic":
        from .anthropic_client import AnthropicClient

        return AnthropicClient(model, cache=cache)
    if provider == "openai":
        from .openai_client import OpenAIClient

        return OpenAIClient(model, cache=cache)
    raise ValueError(f"unknown provider: {provider!r} (use mock|anthropic|openai)")


__all__ = ["LLMClient", "LLMResponse", "DiskCache", "MockLLMClient", "build_client"]
