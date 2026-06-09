"""The public entry point: :class:`SchemaBudgetManager`.

A manager wraps a parsed schema and a :class:`~sqltok.select.base.SchemaSelector`
and turns a natural-language question plus a token budget into a compact,
prompt-ready schema context. The default selector is the value-grounded
submodular :class:`~sqltok.select.coverage.CoverageSelector`; the BM25
:class:`~sqltok.select.greedy.RelevanceGreedySelector` is available as a baseline.
"""

from __future__ import annotations

from pathlib import Path

from .context import SchemaContext
from .ddl import parse_ddl
from .introspect import introspect_sqlite
from .models import Schema
from .select.base import SchemaSelector
from .select.coverage import CoverageSelector
from .tokenizer import DEFAULT_ENCODING, TokenCounter


class SchemaBudgetManager:
    """Retrieve a token-budgeted schema context for a Text2SQL prompt.

    Construct one via :meth:`from_sqlite` or :meth:`from_ddl`, then call
    :meth:`build_context` per question. The manager performs no network I/O; the
    LLM is only ever involved downstream in your own prompt.

    Args:
        schema: The schema to serve contexts from.
        encoding_name: ``tiktoken`` encoding used for all token counting.
        selector: The selection strategy. Defaults to the value-grounded
            submodular :class:`CoverageSelector`.
    """

    def __init__(
        self,
        schema: Schema,
        *,
        encoding_name: str = DEFAULT_ENCODING,
        selector: SchemaSelector | None = None,
    ) -> None:
        self.schema = schema
        self.counter = TokenCounter(encoding_name)
        self.selector: SchemaSelector = (
            selector if selector is not None else CoverageSelector(schema)
        )

    # -- constructors ---------------------------------------------------------

    @classmethod
    def from_sqlite(
        cls,
        db_path: str | Path,
        *,
        sample_rows: int = 3,
        encoding_name: str = DEFAULT_ENCODING,
        selector: SchemaSelector | None = None,
    ) -> SchemaBudgetManager:
        """Build a manager by introspecting a SQLite database file.

        Args:
            db_path: Path to the SQLite database.
            sample_rows: Rows to sample per table for values/example rows.
            encoding_name: ``tiktoken`` encoding name.
            selector: Optional selection strategy override.
        """
        schema = introspect_sqlite(db_path, sample_rows=sample_rows)
        return cls(schema, encoding_name=encoding_name, selector=selector)

    @classmethod
    def from_ddl(
        cls,
        ddl: str,
        *,
        dialect: str | None = None,
        encoding_name: str = DEFAULT_ENCODING,
        selector: SchemaSelector | None = None,
    ) -> SchemaBudgetManager:
        """Build a manager from raw ``CREATE TABLE`` DDL.

        Args:
            ddl: One or more ``CREATE TABLE`` statements.
            dialect: Optional ``sqlglot`` dialect name.
            encoding_name: ``tiktoken`` encoding name.
            selector: Optional selection strategy override.
        """
        schema = parse_ddl(ddl, dialect=dialect)
        return cls(schema, encoding_name=encoding_name, selector=selector)

    # -- core API -------------------------------------------------------------

    def build_context(
        self,
        question: str,
        *,
        token_budget: int = 2000,
        include_sample_rows: bool = True,
        fk_expand: bool = True,
    ) -> SchemaContext:
        """Build a token-budgeted schema context for ``question``.

        Args:
            question: The natural-language question to retrieve schema for.
            token_budget: Hard ceiling on schema-context tokens. The returned
                ``token_count`` is guaranteed not to exceed this.
            include_sample_rows: Attach one example row per included table when
                it fits within budget.
            fk_expand: Add foreign-key bridge/neighbour tables so the selection
                is join-connected, budget permitting.

        Returns:
            A :class:`SchemaContext` with the rendered text, selected tables, and
            measured token count.
        """
        if token_budget <= 0:
            raise ValueError("token_budget must be positive")
        return self.selector.select(
            question,
            token_budget=token_budget,
            counter=self.counter,
            include_sample_rows=include_sample_rows,
            fk_expand=fk_expand,
        )

    def full_schema_text(self, *, include_sample_rows: bool = True) -> str:
        """Return the entire schema as DDL (the benchmark *baseline* dump)."""
        return self.schema.render_full_ddl(include_sample_rows=include_sample_rows)

    def count_tokens(self, text: str) -> int:
        """Count tokens in ``text`` with this manager's encoding."""
        return self.counter.count(text)
