"""The public entry point: :class:`SchemaBudgetManager`.

A manager wraps a parsed schema and a :class:`~sqltok.select.base.SchemaSelector`
and turns a natural-language question plus a token budget into a compact,
prompt-ready schema context. The default selector is the value-grounded
submodular :class:`~sqltok.select.coverage.CoverageSelector`; the BM25
:class:`~sqltok.select.greedy.RelevanceGreedySelector` is available as a baseline.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .context import SchemaContext
from .ddl import parse_ddl
from .escalation import DecisionState, EscalatedCase, EscalationEvidence, EscalationPolicy
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
        escalation_policy: EscalationPolicy | None = None,
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
            escalation_policy: Optional declared-in-advance escalation contract
                (:class:`~sqltok.escalation.EscalationPolicy`). When given, the
                built context is evaluated against the declared paths; if one
                fires, the returned context carries
                ``decision_state=ESCALATED`` and its
                :class:`~sqltok.escalation.EscalatedCase`. The built selection
                stays attached for the arbiter's inspection — consumers must
                branch on ``decision_state`` rather than reading the tables
                blindly. ``None`` (default) preserves the legacy behaviour:
                the context is always ``SERVED``.

        Returns:
            A :class:`SchemaContext` with the rendered text, selected tables,
            measured token count, and its first-class protocol outcome.
        """
        if token_budget <= 0:
            raise ValueError("token_budget must be positive")
        ctx = self.selector.select(
            question,
            token_budget=token_budget,
            counter=self.counter,
            include_sample_rows=include_sample_rows,
            fk_expand=fk_expand,
        )
        if escalation_policy is None:
            return ctx
        case = escalation_policy.evaluate(question, _evidence_from(ctx))
        if case is None:
            return ctx
        return _stamp_escalated(ctx, case)

    def full_schema_text(self, *, include_sample_rows: bool = True) -> str:
        """Return the entire schema as DDL (the benchmark *baseline* dump)."""
        return self.schema.render_full_ddl(include_sample_rows=include_sample_rows)

    def count_tokens(self, text: str) -> int:
        """Count tokens in ``text`` with this manager's encoding."""
        return self.counter.count(text)


def _evidence_from(ctx: SchemaContext) -> EscalationEvidence:
    """Assemble escalation evidence from a built context.

    Coverage participates only when the selector actually reported it
    (:attr:`SchemaContext.coverage_reported`); a selector that never computes
    coverage must not trip the ``LOW_COVERAGE`` path on its default ``0.0``.
    """
    return EscalationEvidence(
        mention_count=ctx.grounded_mentions,
        tables_selected=len(ctx.tables),
        covered_weight=ctx.covered_weight if ctx.coverage_reported else None,
        top_scores=ctx.top_scores,
    )


def _stamp_escalated(ctx: SchemaContext, case: EscalatedCase) -> SchemaContext:
    """Return a copy of ``ctx`` stamped with its escalation outcome.

    :func:`dataclasses.replace` re-runs the context's ``__post_init__``, so the
    state/record invariant is re-checked on the stamped copy, not trusted.
    """
    stamped = replace(ctx, decision_state=DecisionState.ESCALATED, escalation=case)
    assert stamped.decision_state is DecisionState.ESCALATED
    return stamped
