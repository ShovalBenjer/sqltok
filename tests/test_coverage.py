"""Tests for the submodular CoverageSelector (SQLTok's default)."""

from __future__ import annotations

import pytest

from sqltok import CoverageSelector, SchemaBudgetManager, parse_ddl
from sqltok.tokenizer import TokenCounter


@pytest.mark.parametrize("budget", [40, 100, 250, 600, 1500])
def test_coverage_never_exceeds_budget(sample_db, budget: int) -> None:
    mgr = SchemaBudgetManager.from_sqlite(str(sample_db))
    ctx = mgr.build_context("order amount by product category", token_budget=budget)
    assert ctx.token_count <= budget
    assert ctx.token_count == TokenCounter().count(ctx.text)


def test_coverage_is_deterministic(sample_db) -> None:
    mgr = SchemaBudgetManager.from_sqlite(str(sample_db))
    q = "order amount by customer country"
    a = mgr.build_context(q, token_budget=300)
    b = mgr.build_context(q, token_budget=300)
    assert a.tables == b.tables
    assert a.text == b.text
    assert a.token_count == b.token_count


def test_coverage_selects_value_grounded_table() -> None:
    ddl = """
    CREATE TABLE products (id INTEGER PRIMARY KEY, sku TEXT, category TEXT);
    CREATE TABLE employees (id INTEGER PRIMARY KEY, fullname TEXT, title TEXT);
    CREATE TABLE buildings (id INTEGER PRIMARY KEY, address TEXT);
    """
    schema = parse_ddl(ddl)
    schema.tables["products"].columns[2].sample_values = ["widgets", "gadgets"]
    selector = CoverageSelector(schema)
    ctx = selector.select("count of widgets", token_budget=200, counter=TokenCounter())
    assert "products" in ctx.tables
    assert ctx.covered_weight > 0.0


def test_coverage_reports_covered_weight_fraction(sample_db) -> None:
    mgr = SchemaBudgetManager.from_sqlite(str(sample_db))
    ctx = mgr.build_context("order amount by customer country", token_budget=4000)
    assert 0.0 < ctx.covered_weight <= 1.0


def test_coverage_fallback_when_no_grounding(sample_db) -> None:
    # A question with no lexical/value overlap still yields a budget-safe context
    # (smallest-tables-first fallback), never an exception.
    mgr = SchemaBudgetManager.from_sqlite(str(sample_db))
    ctx = mgr.build_context("zzzqqq xyzzy", token_budget=200)
    assert ctx.token_count <= 200


def test_coverage_prefers_fewer_redundant_tables() -> None:
    # Two tables redundantly cover the same mention; a third covers a distinct
    # one. Under a budget for two tables, coverage should not pick both redundant
    # tables when a distinct-coverage table is available.
    ddl = """
    CREATE TABLE sales_a (id INTEGER PRIMARY KEY, revenue REAL);
    CREATE TABLE sales_b (id INTEGER PRIMARY KEY, revenue REAL);
    CREATE TABLE regions (id INTEGER PRIMARY KEY, region TEXT);
    """
    schema = parse_ddl(ddl)
    selector = CoverageSelector(schema)
    counter = TokenCounter()
    # Budget for ~two small tables.
    two = counter.count(
        schema.tables["sales_a"].render_ddl() + "\n\n" + schema.tables["regions"].render_ddl()
    )
    ctx = selector.select("revenue by region", token_budget=two + 5, counter=counter)
    assert "regions" in ctx.tables
    # Exactly one of the redundant revenue tables suffices for coverage.
    assert not ({"sales_a", "sales_b"} <= set(ctx.tables))
