"""Local, keyless provider using Ollama (https://ollama.com).

Runs against a local Ollama server, so execution-accuracy benchmarks need no
OpenAI or Anthropic key and cost nothing. Start Ollama and pull a model first,
for example: `ollama pull qwen2.5-coder:7b`. Uses only the standard library.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .base import LLMClient, LLMResponse


class OllamaClient(LLMClient):
    """Calls a local Ollama server's chat API. Free, no API key."""

    input_price_per_m = 0.0
    output_price_per_m = 0.0

    def __init__(self, model: str, *, cache=None, max_tokens: int = 512) -> None:  # noqa: ANN001
        super().__init__(model, cache=cache)
        self.max_tokens = max_tokens
        self.host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")

    @property
    def provider(self) -> str:
        return "ollama"

    def _complete(self, system: str, prompt: str) -> LLMResponse:
        payload = {
            "model": self.model,
            "stream": False,
            "options": {"num_predict": self.max_tokens, "temperature": 0},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        req = urllib.request.Request(
            f"{self.host}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"could not reach Ollama at {self.host}: {exc.reason}. "
                "Is `ollama serve` running and the model pulled?"
            ) from exc
        return LLMResponse(
            text=data.get("message", {}).get("content", ""),
            input_tokens=int(data.get("prompt_eval_count", 0)),
            output_tokens=int(data.get("eval_count", 0)),
            model=self.model,
        )
