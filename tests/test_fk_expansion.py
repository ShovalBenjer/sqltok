"""Tests for foreign-key neighbour expansion in the baseline selector."""

from __future__ import annotations

from sqltok import RelevanceGreedySelector, parse_ddl
from sqltok.tokenizer import TokenCounter


def test_fk_neighbors_are_bidirectional(sample_ddl: str) -> None:
    schema = parse_ddl(sample_ddl)
    # orders references customers; line_items references orders.
    assert schema.fk_neighbors("orders") == ["customers", "line_items"]
    # products is referenced by line_items only.
    assert schema.fk_neighbors("products") == ["line_items"]


def test_fk_expansion_pulls_in_related_table() -> None:
    # A question that lexically matches only "orders". With the candidate scan
    # capped to the single top-ranked table, "customers" falls outside the
    # window -- but FK expansion still pulls it in, while "unrelated" stays out.
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
    schema = parse_ddl(ddl)
    selector = RelevanceGreedySelector(schema, max_candidates=1)
    ctx = selector.select("orders total", token_budget=4000, counter=TokenCounter())
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
    schema = parse_ddl(ddl)
    selector = RelevanceGreedySelector(schema, max_candidates=1)
    ctx = selector.select(
        "orders total", token_budget=4000, counter=TokenCounter(), fk_expand=False
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
    schema = parse_ddl(ddl)
    counter = TokenCounter()
    orders_tokens = counter.count(schema.tables["orders"].render_ddl())
    selector = RelevanceGreedySelector(schema, max_candidates=1)
    ctx = selector.select("orders total", token_budget=orders_tokens + 1, counter=counter)
    assert ctx.token_count <= orders_tokens + 1
    assert "orders" in ctx.tables
