"""The result object returned by :meth:`SchemaBudgetManager.build_context`."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class SchemaContext:
    """A budget-constrained schema context ready to drop into an LLM prompt.

    Attributes:
        text: The compact ``CREATE TABLE``-style schema string.
        tables: Selected table names, in rendered order.
        token_count: Real token count of ``text`` (measured with ``tiktoken``).
        budget: The token budget the context was built against.
        encoding_name: The ``tiktoken`` encoding used to measure tokens.
        fk_expanded: Tables that were added purely by foreign-key expansion
            (i.e. not selected by the retriever directly).
    """

    text: str
    tables: list[str]
    token_count: int
    budget: int
    encoding_name: str
    fk_expanded: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return self.text
