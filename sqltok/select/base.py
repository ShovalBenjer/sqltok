"""The selector seam plus shared budget-packing primitives.

A :class:`SchemaSelector` turns a question + token budget into a
:class:`~sqltok.context.SchemaContext`. Every selector shares the same
budget-safety machinery here: tables are rendered and *re-measured* with
``tiktoken`` on each tentative add, so the returned context can never exceed the
budget regardless of how a selector chooses tables.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ..models import Schema
from ..tokenizer import TokenCounter

if TYPE_CHECKING:
    from ..context import SchemaContext

_SEPARATOR = "\n\n"


@runtime_checkable
class SchemaSelector(Protocol):
    """Protocol for schema-context selection strategies."""

    name: str

    def select(
        self,
        question: str,
        *,
        token_budget: int,
        counter: TokenCounter,
        include_sample_rows: bool = True,
        fk_expand: bool = True,
    ) -> SchemaContext: ...


class BudgetPacker:
    """Renders selected tables and enforces the hard token ceiling.

    Holds the mutable selection state (ordered table names + per-table sample-row
    flags) and exposes :meth:`try_add`, which only commits a table if the *full*
    re-rendered context still fits the budget.
    """

    def __init__(
        self,
        schema: Schema,
        *,
        token_budget: int,
        counter: TokenCounter,
        include_sample_rows: bool,
    ) -> None:
        self.schema = schema
        self.token_budget = token_budget
        self.counter = counter
        self.include_sample_rows = include_sample_rows
        self.selected: list[str] = []
        self.sample_flags: dict[str, bool] = {}

    def render(self) -> str:
        """Render the current selection to a single context string."""
        return _SEPARATOR.join(
            self.schema.tables[name].render_ddl(
                include_sample_row=self.sample_flags.get(name, False)
            )
            for name in self.selected
        )

    def token_count(self) -> int:
        """Real token count of the current selection."""
        return self.counter.count(self.render())

    def standalone_cost(self, name: str) -> int:
        """Token cost of a single table in isolation (a packing cost proxy)."""
        table = self.schema.tables[name]
        return self.counter.count(
            table.render_ddl(include_sample_row=self.include_sample_rows)
        )

    def contains(self, name: str) -> bool:
        return name in self.sample_flags

    def try_add(self, name: str) -> bool:
        """Add ``name`` iff the resulting context still fits the budget.

        Prefers including the table's sample row, falling back to no row rather
        than dropping the table entirely. Returns whether the table was added.
        """
        if name in self.sample_flags or name not in self.schema.tables:
            return False
        options = (True, False) if self.include_sample_rows else (False,)
        for want_sample in options:
            self.sample_flags[name] = want_sample
            self.selected.append(name)
            if self.token_count() <= self.token_budget:
                return True
            # Roll back and try the next (cheaper) option.
            self.selected.pop()
        self.sample_flags.pop(name, None)
        return False
