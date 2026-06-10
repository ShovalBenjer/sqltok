"""Relevance-greedy baseline selector (BM25 ranking + FK expansion).

This is the honest *floor* SQLTok's coverage selector is measured against: rank
tables by a keyword retriever, greedily pack them under the budget, then pull in
foreign-key neighbours of the candidate window. It is intentionally simple so
that benchmark gains can be attributed to the coverage/grounding machinery.
"""

from __future__ import annotations

from ..context import SchemaContext
from ..models import Schema
from ..retrieval import TableRetriever
from ..tokenizer import TokenCounter
from .base import BudgetPacker


class RelevanceGreedySelector:
    """Greedy top-ranked packing with foreign-key expansion.

    Args:
        schema: The schema to select from.
        retriever: A prebuilt :class:`TableRetriever`; one is created if omitted.
        max_candidates: Cap on the number of top-ranked tables considered during
            the greedy fill (foreign-key expansion can still reach beyond it).
    """

    name = "relevance_greedy"

    def __init__(
        self,
        schema: Schema,
        *,
        retriever: TableRetriever | None = None,
        max_candidates: int | None = None,
    ) -> None:
        self.schema = schema
        self.retriever = retriever if retriever is not None else TableRetriever(schema)
        self.max_candidates = max_candidates

    def select(
        self,
        question: str,
        *,
        token_budget: int,
        counter: TokenCounter,
        include_sample_rows: bool = True,
        fk_expand: bool = True,
    ) -> SchemaContext:
        """Build a budgeted schema context by greedy relevance packing."""
        ranked = self.retriever.rank(question)
        candidates = ranked if self.max_candidates is None else ranked[: self.max_candidates]

        packer = BudgetPacker(
            self.schema,
            token_budget=token_budget,
            counter=counter,
            include_sample_rows=include_sample_rows,
        )
        for rt in candidates:
            packer.try_add(rt.name)

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
            selector=self.name,
            fk_expanded=fk_added,
        )
