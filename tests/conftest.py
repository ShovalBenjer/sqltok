"""Shared pytest fixtures: a small in-memory schema and a sample SQLite DB."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

SAMPLE_DDL = """
CREATE TABLE customers (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  region TEXT
);
CREATE TABLE orders (
  id INTEGER PRIMARY KEY,
  customer_id INTEGER,
  amount REAL,
  order_date TEXT,
  FOREIGN KEY (customer_id) REFERENCES customers(id)
);
CREATE TABLE line_items (
  id INTEGER PRIMARY KEY,
  order_id INTEGER,
  product_id INTEGER,
  qty INTEGER NOT NULL,
  FOREIGN KEY (order_id) REFERENCES orders(id),
  FOREIGN KEY (product_id) REFERENCES products(id)
);
CREATE TABLE products (
  id INTEGER PRIMARY KEY,
  sku TEXT,
  price REAL,
  category TEXT
);
CREATE TABLE suppliers (
  id INTEGER PRIMARY KEY,
  company TEXT,
  country TEXT
);
"""


@pytest.fixture
def sample_ddl() -> str:
    return SAMPLE_DDL


@pytest.fixture
def sample_db(tmp_path: Path) -> Path:
    """Create a populated SQLite database and return its path."""
    db_path = tmp_path / "sample.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(SAMPLE_DDL)
    conn.executescript(
        """
        INSERT INTO customers VALUES (1, 'Acme Corp', 'North'), (2, 'Globex', 'South');
        INSERT INTO orders VALUES (1, 1, 99.5, '2026-01-05'), (2, 2, 150.0, '2026-02-01');
        INSERT INTO products VALUES (1, 'SKU-1', 9.99, 'widgets'), (2, 'SKU-2', 19.99, 'gadgets');
        INSERT INTO line_items VALUES (1, 1, 1, 3), (2, 1, 2, 1);
        INSERT INTO suppliers VALUES (1, 'Initech', 'USA');
        """
    )
    conn.commit()
    conn.close()
    return db_path
