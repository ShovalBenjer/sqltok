"""Greedy, budget-aware schema selection.

Given a ranked list of tables, greedily add each table's DDL (optionally with a
sample row) while the *measured* token count of the full rendered context stays
at or below the budget, then expand along foreign keys. The budget is a hard
ceiling: the returned context is always re-measured against the same tokenizer,
so it can never exceed ``token_budget``.
"""

from __future__ import annotations

from .context import SchemaContext
from .models import Schema
from .retrieval import RankedTable
from .tokenizer import TokenCounter

_SEPARATOR = "\n\n"


def _render(schema: Schema, selected: list[str], sample_flags: dict[str, bool]) -> str:
    """Render the selected tables (in order) into a single context string."""
    blocks = [
        schema.tables[name].render_ddl(include_sample_row=sample_flags.get(name, False))
        for name in selected
    ]
    return _SEPARATOR.join(blocks)


def build_budgeted_context(
    schema: Schema,
    ranked: list[RankedTable],
    *,
    token_budget: int,
    counter: TokenCounter,
    include_sample_rows: bool = True,
    fk_expand: bool = True,
    max_candidates: int | None = None,
) -> SchemaContext:
    """Select tables greedily under a hard token budget.

    Args:
        schema: The full schema.
        ranked: Tables ordered by descending relevance.
        token_budget: Hard ceiling on the rendered context's token count.
        counter: The :class:`TokenCounter` used for every measurement.
        include_sample_rows: Whether to try to attach one sample row per table.
            If a table fits without its sample row but not with it, the row is
            dropped for that table rather than dropping the whole table.
        fk_expand: If ``True``, after greedy selection, also pull in tables that
            are foreign-key neighbours of selected tables, budget permitting.
        max_candidates: If set, only the top-``max_candidates`` ranked tables are
            considered during the greedy fill. Foreign-key expansion may still
            pull in connected tables that fall outside this window -- which is
            the point of the feature on wide schemas where scanning every table
            is wasteful.

    Returns:
        A :class:`SchemaContext` whose ``token_count`` is guaranteed ``<=``
        ``token_budget``.
    """
    candidates = ranked if max_candidates is None else ranked[:max_candidates]
    selected: list[str] = []
    sample_flags: dict[str, bool] = {}
    fk_added: list[str] = []

    def fits(candidate_selected: list[str], candidate_flags: dict[str, bool]) -> int | None:
        text = _render(schema, candidate_selected, candidate_flags)
        tokens = counter.count(text)
        return tokens if tokens <= token_budget else None

    def try_add(name: str) -> bool:
        if name in sample_flags:
            return False
        # Prefer including the sample row, but fall back to no row if needed.
        for want_sample in ((True, False) if include_sample_rows else (False,)):
            trial_flags = dict(sample_flags)
            trial_flags[name] = want_sample
            if fits([*selected, name], trial_flags) is not None:
                selected.append(name)
                sample_flags[name] = want_sample
                return True
        return False

    for ranked_table in candidates:
        try_add(ranked_table.name)

    if fk_expand:
        # Iterate over a snapshot: only expand from retriever-selected tables.
        for name in list(selected):
            for neighbor in schema.fk_neighbors(name):
                if neighbor not in sample_flags and try_add(neighbor):
                    fk_added.append(neighbor)

    text = _render(schema, selected, sample_flags)
    token_count = counter.count(text)
    return SchemaContext(
        text=text,
        tables=list(selected),
        token_count=token_count,
        budget=token_budget,
        encoding_name=counter.encoding_name,
        fk_expanded=fk_added,
    )
