"""Tests for the token budget guarantee."""

from __future__ import annotations

import pytest

from sqltok import SchemaBudgetManager
from sqltok.tokenizer import TokenCounter


@pytest.mark.parametrize("budget", [50, 100, 200, 400, 800, 2000])
def test_context_never_exceeds_budget(sample_ddl: str, budget: int) -> None:
    mgr = SchemaBudgetManager.from_ddl(sample_ddl)
    ctx = mgr.build_context("order amount by region and product category", token_budget=budget)
    # The reported count is honest...
    counter = TokenCounter()
    assert ctx.token_count == counter.count(ctx.text)
    # ...and never exceeds the hard ceiling.
    assert ctx.token_count <= budget


def test_larger_budget_includes_at_least_as_many_tables(sample_ddl: str) -> None:
    mgr = SchemaBudgetManager.from_ddl(sample_ddl)
    q = "order amount by customer region"
    small = mgr.build_context(q, token_budget=120)
    large = mgr.build_context(q, token_budget=4000)
    assert set(small.tables).issubset(set(large.tables))
    assert len(large.tables) >= len(small.tables)


def test_tiny_budget_yields_empty_or_single(sample_ddl: str) -> None:
    mgr = SchemaBudgetManager.from_ddl(sample_ddl)
    ctx = mgr.build_context("anything", token_budget=10)
    assert ctx.token_count <= 10
    assert len(ctx.tables) <= 1


def test_sample_rows_increase_or_equal_tokens(sample_db) -> None:
    mgr = SchemaBudgetManager.from_sqlite(str(sample_db))
    q = "order amount by customer region"
    with_rows = mgr.build_context(q, token_budget=4000, include_sample_rows=True)
    without = mgr.build_context(q, token_budget=4000, include_sample_rows=False)
    assert with_rows.token_count >= without.token_count
    assert "example row" in with_rows.text
    assert "example row" not in without.text


def test_zero_budget_raises(sample_ddl: str) -> None:
    mgr = SchemaBudgetManager.from_ddl(sample_ddl)
    with pytest.raises(ValueError):
        mgr.build_context("x", token_budget=0)
