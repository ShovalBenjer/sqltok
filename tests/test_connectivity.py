"""Tests for foreign-key Steiner connectivity in the coverage selector."""

from __future__ import annotations

from sqltok import CoverageSelector, parse_ddl
from sqltok.select.base import BudgetPacker
from sqltok.select.connect import connect_selection
from sqltok.tokenizer import TokenCounter


def test_steiner_bridge_connects_disjoint_tables() -> None:
    # products and orders are not directly FK-connected; line_items bridges them.
    ddl = """
    CREATE TABLE products (id INTEGER PRIMARY KEY, category TEXT);
    CREATE TABLE line_items (
      id INTEGER PRIMARY KEY,
      order_id INTEGER,
      product_id INTEGER,
      FOREIGN KEY (order_id) REFERENCES orders(id),
      FOREIGN KEY (product_id) REFERENCES products(id)
    );
    CREATE TABLE orders (id INTEGER PRIMARY KEY, amount REAL);
    """
    schema = parse_ddl(ddl)
    counter = TokenCounter()
    packer = BudgetPacker(
        schema, token_budget=4000, counter=counter, include_sample_rows=False
    )
    packer.try_add("products")
    packer.try_add("orders")
    bridges = connect_selection(packer)
    assert "line_items" in bridges
    assert "line_items" in packer.selected


def test_steiner_respects_budget() -> None:
    ddl = """
    CREATE TABLE products (id INTEGER PRIMARY KEY, category TEXT);
    CREATE TABLE line_items (
      id INTEGER PRIMARY KEY,
      order_id INTEGER,
      product_id INTEGER,
      note_a TEXT, note_b TEXT, note_c TEXT,
      FOREIGN KEY (order_id) REFERENCES orders(id),
      FOREIGN KEY (product_id) REFERENCES products(id)
    );
    CREATE TABLE orders (id INTEGER PRIMARY KEY, amount REAL);
    """
    schema = parse_ddl(ddl)
    counter = TokenCounter()
    packer = BudgetPacker(
        schema, token_budget=4000, counter=counter, include_sample_rows=False
    )
    packer.try_add("products")
    packer.try_add("orders")
    budget = packer.token_count() + 2  # no room for the bridge table
    packer.token_budget = budget
    bridges = connect_selection(packer)
    assert bridges == []
    assert packer.token_count() <= budget


def test_no_bridges_when_already_connected() -> None:
    ddl = """
    CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT);
    CREATE TABLE orders (
      id INTEGER PRIMARY KEY,
      customer_id INTEGER,
      FOREIGN KEY (customer_id) REFERENCES customers(id)
    );
    """
    schema = parse_ddl(ddl)
    selector = CoverageSelector(schema)
    ctx = selector.select("customers and orders", token_budget=4000, counter=TokenCounter())
    assert ctx.bridge_tables == []
