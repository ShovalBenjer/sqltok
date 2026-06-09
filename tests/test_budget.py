"""Tests for the token budget guarantee (default coverage selector)."""

from __future__ import annotations

import pytest

from sqltok import SchemaBudgetManager
from sqltok.tokenizer import TokenCounter


@pytest.mark.parametrize("budget", [40, 80, 150, 300, 800, 2000])
def test_context_never_exceeds_budget(sample_db, budget: int) -> None:
    mgr = SchemaBudgetManager.from_sqlite(str(sample_db))
    ctx = mgr.build_context(
        "order amount by customer country and product category", token_budget=budget
    )
    counter = TokenCounter()
    # The reported count is honest...
    assert ctx.token_count == counter.count(ctx.text)
    # ...and never exceeds the hard ceiling.
    assert ctx.token_count <= budget


def test_budget_holds_without_sample_rows(sample_db) -> None:
    mgr = SchemaBudgetManager.from_sqlite(str(sample_db))
    ctx = mgr.build_context("order amount", token_budget=120, include_sample_rows=False)
    assert ctx.token_count <= 120
    assert "example row" not in ctx.text


def test_tiny_budget_yields_empty_or_single(sample_db) -> None:
    mgr = SchemaBudgetManager.from_sqlite(str(sample_db))
    ctx = mgr.build_context("anything at all", token_budget=12)
    assert ctx.token_count <= 12
    assert len(ctx.tables) <= 1


def test_sample_rows_increase_or_equal_tokens(sample_db) -> None:
    mgr = SchemaBudgetManager.from_sqlite(str(sample_db))
    q = "order amount by customer country"
    with_rows = mgr.build_context(q, token_budget=4000, include_sample_rows=True)
    without = mgr.build_context(q, token_budget=4000, include_sample_rows=False)
    assert with_rows.token_count >= without.token_count


def test_zero_budget_raises(sample_db) -> None:
    mgr = SchemaBudgetManager.from_sqlite(str(sample_db))
    with pytest.raises(ValueError):
        mgr.build_context("x", token_budget=0)


def test_selector_name_recorded(sample_db) -> None:
    mgr = SchemaBudgetManager.from_sqlite(str(sample_db))
    ctx = mgr.build_context("order amount", token_budget=300)
    assert ctx.selector == "coverage"
