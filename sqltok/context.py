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
        selector: Name of the selection strategy that produced this context.
        bridge_tables: Tables added purely to make the selection join-connected
            (foreign-key Steiner bridges), not because they were relevant.
        fk_expanded: Tables added by plain foreign-key expansion (baseline
            selector); kept for backwards compatibility.
        covered_weight: Fraction of total grounded mention weight covered by the
            selection (``0.0`` for selectors that do not compute coverage).
    """

    text: str
    tables: list[str]
    token_count: int
    budget: int
    encoding_name: str
    selector: str = ""
    bridge_tables: list[str] = field(default_factory=list)
    fk_expanded: list[str] = field(default_factory=list)
    covered_weight: float = 0.0

    def __str__(self) -> str:
        return self.text
