"""Adaptive SLM-assisted schema router (ADR-0009: cheap-first, escalate-on-uncertain).

Complements the BM25 baseline (:class:`RelevanceGreedySelector`) with a small
local model reranker behind a calibrated cheap-first router::

    BM25 rank (free) -> uncertainty check -> [escalate] SLM rerank of top-N
    candidates -> schema-check -> budgeted pack + FK expansion

This is the asymmetric-routing pattern from ADR-0009 (evidence: NVIDIA
"SLMs are the Future of Agentic AI", arXiv:2506.02153; FrugalGPT/RouteLLM
cascades): the SLM is a stateless leaf executor for the narrow,
format-constrained rerank task. It never judges, never drives a loop, and its
output is schema-checked before use. Every routing decision (cheap path vs
escalation vs fallback) is logged for threshold calibration.

Backends are pluggable via :class:`SLMBackend`:

* :class:`OllamaSLMBackend` — a local Ollama chat model, JSON-constrained and
  schema-checked. Used when an Ollama server is reachable.
* :class:`HeuristicFallbackBackend` — deterministic synonym/overlap reranker,
  always available. Used when no SLM is reachable or the SLM output fails its
  schema check.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from typing import Protocol, runtime_checkable

from ..context import SchemaContext
from ..models import Schema
from ..retrieval import TableRetriever
from ..tokenizer import TokenCounter
from .base import BudgetPacker

_DEFAULT_MODEL = os.environ.get("SQLTOK_SLM_MODEL", "qwen2.5:1.5b")
_DEFAULT_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")

# Small synonym map for the heuristic fallback. Deliberately tiny and
# domain-flavoured: it only needs to cover the lexical gaps BM25 misses
# (synonyms), not replace a real model.
_SYNONYMS: dict[str, tuple[str, ...]] = {
    "revenue": ("total", "amount", "price", "sales"),
    "earnings": ("total", "amount", "price", "salary", "wage"),
    "profit": ("margin", "total", "amount"),
    "customer": ("client", "buyer", "user"),
    "client": ("customer", "buyer", "user"),
    "order": ("purchase", "transaction"),
    "purchase": ("order", "transaction"),
    "product": ("item", "goods", "merchandise"),
    "item": ("product", "goods"),
    "employee": ("staff", "worker", "personnel"),
    "staff": ("employee", "worker"),
    "student": ("pupil", "learner"),
    "school": ("academy", "institution"),
    "price": ("cost", "amount", "total"),
    "cost": ("price", "amount", "expense"),
    "count": ("number", "quantity", "total"),
    "number": ("count", "quantity"),
    "oldest": ("earliest", "first"),
    "newest": ("latest", "recent"),
    "biggest": ("largest", "max", "maximum"),
    "smallest": ("least", "min", "minimum"),
    "address": ("location", "city", "country"),
    "location": ("address", "city", "country"),
    "stock": ("inventory", "on_hand", "quantity"),
    "value": ("total", "amount", "price"),
    "expensive": ("price", "cost"),
    "cheap": ("price", "cost"),
    "medic": ("doctor", "physician", "surgeon"),
    "specialize": ("specialty",),
    "drugs": ("drug", "medication", "prescription"),
    "prescribed": ("prescription",),
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    raw = set(_TOKEN_RE.findall(text.lower()))
    out = set(raw)
    for tok in raw:
        # Cheap plural-insensitive matching: index both "orders" and "order".
        # Not a stemmer, just the two most common English plural forms.
        if len(tok) > 3 and tok.endswith("ies"):
            out.add(tok[:-3] + "y")
        elif len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
            out.add(tok[:-1])
    return out


def _expand(tokens: set[str]) -> set[str]:
    out = set(tokens)
    for tok in tokens:
        out.update(_SYNONYMS.get(tok, ()))
    return out


@runtime_checkable
class SLMBackend(Protocol):
    """Pluggable rerank backend for the adaptive router."""

    name: str

    def available(self) -> bool:
        """Whether this backend can serve a rerank right now."""
        ...

    def rerank(
        self,
        question: str,
        candidates: list[str],
        *,
        table_docs: dict[str, str],
    ) -> list[str] | None:
        """Return candidates reranked best-first, or ``None`` to decline.

        A backend declines (returns ``None``) instead of returning a dubious
        ranking; the router then falls back down the backend chain.
        """
        ...


class OllamaSLMBackend:
    """Rerank via a local Ollama chat model (keyless, zero marginal cost).

    The model is asked for a strict JSON list of table names; the response is
    schema-checked (valid JSON, known table names only, non-empty) and any
    violation makes the backend decline rather than guess.
    """

    name = "ollama"

    def __init__(self, model: str = _DEFAULT_MODEL, *, host: str = _DEFAULT_HOST) -> None:
        self.model = model
        self.host = host
        self._reachable: bool | None = None

    def available(self) -> bool:
        if self._reachable is None:
            try:
                req = urllib.request.Request(f"{self.host}/api/tags", method="GET")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    self._reachable = resp.status == 200
            except (urllib.error.URLError, OSError, TimeoutError):
                self._reachable = False
        return self._reachable

    def rerank(
        self,
        question: str,
        candidates: list[str],
        *,
        table_docs: dict[str, str],
    ) -> list[str] | None:
        if not self.available():
            return None
        docs = "\n".join(f"- {name}: {table_docs.get(name, '')[:300]}" for name in candidates)
        system = (
            "You rank database tables by relevance to a question. "
            'Reply with ONLY a JSON object like {"tables": ["t1", "t2"]}, '
            "listing the candidate table names from most to least relevant. "
            "No explanation, no markdown."
        )
        prompt = f"Question: {question}\nCandidate tables:\n{docs}"
        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0, "num_predict": 256},
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
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            text = data.get("message", {}).get("content", "")
            parsed = json.loads(text)
        except (urllib.error.URLError, OSError, TimeoutError, ValueError):
            return None
        return _schema_check_ranking(parsed, candidates)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"OllamaSLMBackend(model={self.model!r}, host={self.host!r})"


class HeuristicFallbackBackend:
    """Deterministic synonym/overlap reranker. Always available.

    Scores each candidate by token overlap between the (synonym-expanded)
    question and the table document. This is the honest floor the SLM must
    beat: cheap, offline, and never hallucinates table names.
    """

    name = "heuristic"

    def available(self) -> bool:
        return True

    def rerank(
        self,
        question: str,
        candidates: list[str],
        *,
        table_docs: dict[str, str],
    ) -> list[str] | None:
        q = _expand(_tokens(question))
        if not q:
            return None
        scored = []
        for name in candidates:
            doc = _expand(_tokens(name + " " + table_docs.get(name, "")))
            overlap = len(q & doc)
            # Name-token hits weigh more: the table name is the densest signal.
            name_hits = len(q & _expand(_tokens(name)))
            scored.append((overlap + 2 * name_hits, name))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [name for _, name in scored]


def _schema_check_ranking(parsed: object, candidates: list[str]) -> list[str] | None:
    """Validate an SLM rerank response. Returns the ranking or ``None``.

    The guard is strict on purpose (ADR-0009: every SLM output schema-checked):
    the response must be a JSON object with a non-empty ``tables`` list whose
    entries are all known candidate names. Duplicates are dropped, order kept.
    """
    if not isinstance(parsed, dict):
        return None
    tables = parsed.get("tables")
    if not isinstance(tables, list) or not tables:
        return None
    allowed = set(candidates)
    seen: set[str] = set()
    ranked: list[str] = []
    for entry in tables:
        if not isinstance(entry, str) or entry not in allowed:
            return None  # non-string or hallucinated table: decline the ranking
        if entry in seen:
            continue  # dedupe, keep first occurrence
        seen.add(entry)
        ranked.append(entry)
    if not ranked:
        return None
    # Append any candidates the model omitted, keeping BM25 order for the tail.
    ranked.extend(name for name in candidates if name not in seen)
    return ranked


class SLMSchemaRouter:
    """Cheap-first adaptive schema selector with SLM rerank escalation.

    Args:
        schema: The schema to select from.
        backend: Primary rerank backend. Defaults to :class:`OllamaSLMBackend`
            with :class:`HeuristicFallbackBackend` as the automatic fallback.
        retriever: Prebuilt :class:`TableRetriever`; one is created if omitted.
        max_candidates: How many top-BM25 tables the SLM may rerank.
        uncertainty_margin: Escalate when ``(s1 - s2) < margin * s1`` on the
            normalised BM25 scores, i.e. the top-2 are too close to call, or
            when the top score is zero (nothing matched).
        decisions_log: Optional path for a JSONL decision log (one record per
            :meth:`select`); decisions are always kept in memory too.
    """

    name = "slm_router"

    def __init__(
        self,
        schema: Schema,
        *,
        backend: SLMBackend | None = None,
        fallback: SLMBackend | None = None,
        retriever: TableRetriever | None = None,
        max_candidates: int = 12,
        uncertainty_margin: float = 0.25,
        decisions_log: str | None = None,
    ) -> None:
        self.schema = schema
        self.backend: SLMBackend = backend if backend is not None else OllamaSLMBackend()
        self.fallback: SLMBackend = fallback if fallback is not None else HeuristicFallbackBackend()
        self.retriever = retriever if retriever is not None else TableRetriever(schema)
        self.max_candidates = max_candidates
        self.uncertainty_margin = uncertainty_margin
        self.decisions_log = decisions_log
        self._decisions: list[dict[str, object]] = []

    @property
    def decisions(self) -> list[dict[str, object]]:
        """In-memory log of routing decisions (for threshold calibration)."""
        return list(self._decisions)

    def _log_decision(self, record: dict[str, object]) -> None:
        self._decisions.append(record)
        if self.decisions_log:
            with open(self.decisions_log, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")

    def _uncertain(self, scores: list[float]) -> tuple[bool, float]:
        """Cheap-first uncertainty check on the top BM25 scores.

        Returns ``(uncertain, margin)`` where margin is the normalised top-1/top-2
        gap. Uncertain when nothing matched (top score is 0) or the top two are
        within ``uncertainty_margin`` of each other relative to the top score.
        """
        if not scores or scores[0] <= 0:
            return True, 0.0
        top2 = sorted(scores, reverse=True)[:2]
        gap = top2[0] - (top2[1] if len(top2) > 1 else 0.0)
        margin = gap / top2[0] if top2[0] > 0 else 0.0
        return margin < self.uncertainty_margin, margin

    def _order_tables(self, question: str) -> tuple[list[str], dict[str, object]]:
        ranked = self.retriever.rank(question)
        names = [rt.name for rt in ranked]
        scores = [rt.score for rt in ranked]
        uncertain, margin = self._uncertain(scores)
        docs = {name: self._table_doc(name) for name in names[: self.max_candidates]}

        decision: dict[str, object] = {
            "question_sha256": hashlib.sha256(question.encode()).hexdigest()[:16],
            "bm25_margin": round(margin, 4),
            "uncertain": uncertain,
        }

        if not uncertain:
            decision.update({"path": "cheap", "backend": "bm25"})
            self._log_decision(decision)
            return names, decision

        candidates = names[: self.max_candidates]
        for backend in (self.backend, self.fallback):
            if not backend.available():
                continue
            reranked = backend.rerank(question, candidates, table_docs=docs)
            if reranked:
                tail = [n for n in names if n not in set(reranked)]
                decision.update(
                    {"path": "escalated", "backend": backend.name, "n_candidates": len(candidates)}
                )
                self._log_decision(decision)
                return reranked + tail, decision

        decision.update({"path": "fallback_bm25", "backend": "bm25"})
        self._log_decision(decision)
        return names, decision

    def _table_doc(self, name: str) -> str:
        table = self.schema.tables[name]
        parts = [name]
        if table.description:
            parts.append(table.description)
        parts.extend(table.column_names())
        return " ".join(parts)

    def select(
        self,
        question: str,
        *,
        token_budget: int,
        counter: TokenCounter,
        include_sample_rows: bool = True,
        fk_expand: bool = True,
    ) -> SchemaContext:
        """Build a budgeted schema context, escalating to the SLM when unsure."""
        ordered, decision = self._order_tables(question)

        packer = BudgetPacker(
            self.schema,
            token_budget=token_budget,
            counter=counter,
            include_sample_rows=include_sample_rows,
        )
        for name in ordered:
            packer.try_add(name)

        fk_added: list[str] = []
        if fk_expand:
            for name in list(packer.selected):
                for neighbor in self.schema.fk_neighbors(name):
                    if not packer.contains(neighbor) and packer.try_add(neighbor):
                        fk_added.append(neighbor)

        text = packer.render()
        return SchemaContext(
            text=text,
            tables=list(packer.selected),
            token_count=counter.count(text),
            budget=token_budget,
            encoding_name=counter.encoding_name,
            selector=f"{self.name}/{decision.get('backend', 'bm25')}",
            fk_expanded=fk_added,
        )
