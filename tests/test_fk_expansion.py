"""Tests for foreign-key expansion within the budget."""

from __future__ import annotations

from sqltok import SchemaBudgetManager, parse_ddl


def test_fk_neighbors_are_bidirectional(sample_ddl: str) -> None:
    schema = parse_ddl(sample_ddl)
    # orders references customers; line_items references orders.
    assert schema.fk_neighbors("orders") == ["customers", "line_items"]
    # products is referenced by line_items only.
    assert schema.fk_neighbors("products") == ["line_items"]


def test_fk_expansion_pulls_in_related_table() -> None:
    # A question that lexically matches only "orders". With the candidate scan
    # capped to the single top-ranked table, "customers" falls outside the
    # window -- but because it is FK-connected to the selected "orders", FK
    # expansion still pulls it in (while the unrelated table stays out).
    ddl = """
    CREATE TABLE orders (
      id INTEGER PRIMARY KEY,
      customer_id INTEGER,
      total REAL,
      FOREIGN KEY (customer_id) REFERENCES customers(id)
    );
    CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT);
    CREATE TABLE unrelated (id INTEGER PRIMARY KEY, blob TEXT);
    """
    mgr = SchemaBudgetManager.from_ddl(ddl)
    ctx = mgr.build_context(
        "orders total", token_budget=4000, fk_expand=True, max_candidates=1
    )
    assert ctx.tables[0] == "orders"
    assert "customers" in ctx.tables
    assert "customers" in ctx.fk_expanded
    assert "unrelated" not in ctx.tables


def test_fk_expansion_can_be_disabled() -> None:
    ddl = """
    CREATE TABLE orders (
      id INTEGER PRIMARY KEY,
      customer_id INTEGER,
      total REAL,
      FOREIGN KEY (customer_id) REFERENCES customers(id)
    );
    CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT);
    """
    mgr = SchemaBudgetManager.from_ddl(ddl)
    ctx = mgr.build_context(
        "orders total", token_budget=4000, fk_expand=False, max_candidates=1
    )
    assert ctx.fk_expanded == []
    assert "customers" not in ctx.tables


def test_fk_expansion_respects_budget() -> None:
    ddl = """
    CREATE TABLE orders (
      id INTEGER PRIMARY KEY,
      customer_id INTEGER,
      total REAL,
      FOREIGN KEY (customer_id) REFERENCES customers(id)
    );
    CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, address TEXT, phone TEXT);
    """
    mgr = SchemaBudgetManager.from_ddl(ddl)
    # Budget large enough for orders but not for both.
    orders_only = mgr.build_context("orders total", token_budget=4000)
    tight = mgr.count_tokens(
        parse_ddl(ddl).tables["orders"].render_ddl()
    )
    ctx = mgr.build_context("orders total", token_budget=tight + 1, fk_expand=True)
    assert ctx.token_count <= tight + 1
    assert "orders" in ctx.tables
    assert orders_only  # sanity
