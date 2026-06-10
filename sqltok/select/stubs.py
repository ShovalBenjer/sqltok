"""Typed v0.2 selector stubs.

These declare the interfaces SQLTok intends to grow into — a cross-encoder
reranker stage and an agentic LLM schema navigator (Datalake Agent / AutoLink
style) — without shipping their dependencies in v0.1. They satisfy the
:class:`~sqltok.select.base.SchemaSelector` Protocol's shape but raise on use so
the roadmap is explicit and discoverable in code, not just the README.
"""

from __future__ import annotations

from ..context import SchemaContext
from ..models import Schema
from ..tokenizer import TokenCounter


class RerankSelector:
    """v0.2: rerank coverage candidates with a cross-encoder before packing.

    Planned signal stack: value-grounded coverage shortlist -> cross-encoder /
    LLM reranker (e.g. bge-reranker-v2, Cohere/Voyage rerank) -> budgeted pack.
    """

    name = "rerank"

    def __init__(self, schema: Schema, *, reranker: object | None = None) -> None:
        self.schema = schema
        self.reranker = reranker

    def select(
        self,
        question: str,
        *,
        token_budget: int,
        counter: TokenCounter,
        include_sample_rows: bool = True,
        fk_expand: bool = True,
    ) -> SchemaContext:
        raise NotImplementedError(
            "RerankSelector is a v0.2 stub. Use CoverageSelector (default) for now."
        )


class AgenticSelector:
    """v0.2: LLM-driven lazy schema discovery (Datalake Agent / AutoLink style).

    Planned: an LLM iteratively requests tables/columns down the schema
    hierarchy, tracing foreign-key bridges, with diminishing-returns stopping —
    trading extra LLM calls for higher recall on very wide warehouses. Kept out
    of core v0.1 because it requires network/LLM access.
    """

    name = "agentic"

    def __init__(self, schema: Schema, *, llm: object | None = None) -> None:
        self.schema = schema
        self.llm = llm

    def select(
        self,
        question: str,
        *,
        token_budget: int,
        counter: TokenCounter,
        include_sample_rows: bool = True,
        fk_expand: bool = True,
    ) -> SchemaContext:
        raise NotImplementedError(
            "AgenticSelector is a v0.2 stub; it requires an LLM and network access."
        )
