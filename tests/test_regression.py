"""Regression tests: pin selection on fixed inputs so behavior cannot drift.

Unlike the property tests, which check invariants, these freeze the exact tables
selected for specific (schema, question, budget) cases. If a change to grounding
or selection silently alters what gets picked, one of these fails and forces a
deliberate decision.
"""

from __future__ import annotations

from sqltok import SchemaBudgetManager
from sqltok.tokenizer import TokenCounter

_DDL = """
CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, country TEXT);
CREATE TABLE orders (
  id INTEGER PRIMARY KEY, customer_id INTEGER, amount REAL, order_date TEXT,
  FOREIGN KEY (customer_id) REFERENCES customers(id)
);
CREATE TABLE line_items (
  id INTEGER PRIMARY KEY, order_id INTEGER, product_id INTEGER, qty INTEGER,
  FOREIGN KEY (order_id) REFERENCES orders(id),
  FOREIGN KEY (product_id) REFERENCES products(id)
);
CREATE TABLE products (id INTEGER PRIMARY KEY, sku TEXT, price REAL, category TEXT);
CREATE TABLE suppliers (id INTEGER PRIMARY KEY, company TEXT, nation TEXT);
"""


def _tables(question: str, budget: int) -> list[str]:
    mgr = SchemaBudgetManager.from_ddl(_DDL)
    return sorted(mgr.build_context(question, token_budget=budget).tables)


def test_snapshot_orders_by_customer() -> None:
    # orders grounds, customers is its FK neighbour, and line_items is pulled in
    # by FK expansion as another neighbour of orders.
    assert _tables("total order amount by customer", 4000) == [
        "customers",
        "line_items",
        "orders",
    ]


def test_snapshot_supplier_query_isolates_suppliers() -> None:
    # suppliers has no FK edges, so it stands alone.
    assert _tables("supplier company by nation", 4000) == ["suppliers"]


def test_snapshot_is_stable_across_calls() -> None:
    q = "products in each order"
    first = _tables(q, 4000)
    for _ in range(3):
        assert _tables(q, 4000) == first


def test_snapshot_budget_monotonic_token_count() -> None:
    mgr = SchemaBudgetManager.from_ddl(_DDL)
    counter = TokenCounter()
    q = "order amount by customer country and product category"
    small = mgr.build_context(q, token_budget=120)
    large = mgr.build_context(q, token_budget=4000)
    assert small.token_count <= 120
    assert large.token_count <= 4000
    assert large.token_count >= small.token_count
    assert small.token_count == counter.count(small.text)
