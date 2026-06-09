"""Tests for DDL parsing."""

from __future__ import annotations

from sqltok import parse_ddl


def test_parse_basic_columns_and_pk(sample_ddl: str) -> None:
    schema = parse_ddl(sample_ddl)
    assert set(schema.table_names()) == {
        "customers",
        "orders",
        "line_items",
        "products",
        "suppliers",
    }
    customers = schema.get("customers")
    assert customers is not None
    names = customers.column_names()
    assert names == ["id", "name", "region"]
    id_col = customers.columns[0]
    assert id_col.primary_key is True
    name_col = customers.columns[1]
    assert name_col.nullable is False  # NOT NULL


def test_parse_inline_and_table_foreign_keys(sample_ddl: str) -> None:
    schema = parse_ddl(sample_ddl)
    orders = schema.get("orders")
    assert orders is not None
    assert len(orders.foreign_keys) == 1
    fk = orders.foreign_keys[0]
    assert (fk.column, fk.ref_table, fk.ref_column) == ("customer_id", "customers", "id")

    line_items = schema.get("line_items")
    assert line_items is not None
    edges = {(f.column, f.ref_table) for f in line_items.foreign_keys}
    assert edges == {("order_id", "orders"), ("product_id", "products")}


def test_inline_references_constraint() -> None:
    ddl = """
    CREATE TABLE a (id INTEGER PRIMARY KEY);
    CREATE TABLE b (id INTEGER PRIMARY KEY, a_id INTEGER REFERENCES a(id));
    """
    schema = parse_ddl(ddl)
    b = schema.get("b")
    assert b is not None
    assert b.foreign_keys[0].ref_table == "a"
    assert b.foreign_keys[0].ref_column == "id"


def test_non_create_statements_are_ignored() -> None:
    ddl = "CREATE TABLE a (id INT); SELECT 1; INSERT INTO a VALUES (1);"
    schema = parse_ddl(ddl)
    assert schema.table_names() == ["a"]


def test_render_ddl_roundtrips_key_facts(sample_ddl: str) -> None:
    schema = parse_ddl(sample_ddl)
    orders = schema.get("orders")
    assert orders is not None
    text = orders.render_ddl()
    assert "CREATE TABLE orders" in text
    assert "PRIMARY KEY" in text
    assert "FOREIGN KEY (customer_id) REFERENCES customers(id)" in text
