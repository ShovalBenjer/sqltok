"""Thin, provider-agnostic LLM interface with on-disk response caching.

The benchmark only ever talks to an LLM through :class:`LLMClient`. Responses are
cached to disk keyed by a hash of (provider, model, system, prompt) so reruns are
free and a run is fully resumable. The mock client makes the whole harness
exercisable without any API keys.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class LLMResponse:
    """A single completion plus token accounting."""

    text: str
    input_tokens: int
    output_tokens: int
    model: str
    cached: bool = False


class DiskCache:
    """A trivial JSON file cache keyed by a content hash."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(provider: str, model: str, system: str, prompt: str) -> str:
        h = hashlib.sha256()
        for part in (provider, model, system, prompt):
            h.update(part.encode("utf-8"))
            h.update(b"\x00")
        return h.hexdigest()

    def get(self, key: str) -> LLMResponse | None:
        path = self.root / f"{key}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return LLMResponse(**data, cached=True)

    def put(self, key: str, response: LLMResponse) -> None:
        path = self.root / f"{key}.json"
        payload = {k: v for k, v in asdict(response).items() if k != "cached"}
        path.write_text(json.dumps(payload))


class LLMClient(ABC):
    """Base class for chat-style LLM providers."""

    #: USD per 1M input / output tokens; override per provider/model.
    input_price_per_m: float = 0.0
    output_price_per_m: float = 0.0

    def __init__(self, model: str, *, cache: DiskCache | None = None) -> None:
        self.model = model
        self.cache = cache

    @property
    @abstractmethod
    def provider(self) -> str:
        """Short provider identifier (used in the cache key)."""

    @abstractmethod
    def _complete(self, system: str, prompt: str) -> LLMResponse:
        """Provider-specific completion (no caching)."""

    def complete(self, system: str, prompt: str) -> LLMResponse:
        """Return a completion, served from cache when available."""
        if self.cache is not None:
            key = DiskCache.key(self.provider, self.model, system, prompt)
            hit = self.cache.get(key)
            if hit is not None:
                return hit
            response = self._complete(system, prompt)
            self.cache.put(key, response)
            return response
        return self._complete(system, prompt)

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        """Estimated USD cost for the given token counts."""
        return (
            input_tokens * self.input_price_per_m
            + output_tokens * self.output_price_per_m
        ) / 1_000_000
