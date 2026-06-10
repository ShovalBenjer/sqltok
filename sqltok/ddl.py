"""Parse ``CREATE TABLE`` DDL into the SQLTok schema model using ``sqlglot``.

This supports the common subset needed for schema-context building: column names
and types, primary keys (inline ``PRIMARY KEY`` and table-level
``PRIMARY KEY (...)``), ``NOT NULL``, inline ``REFERENCES`` and table-level
``FOREIGN KEY (...) REFERENCES ...`` constraints.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp

from .models import Column, ForeignKey, Schema, Table


def parse_ddl(ddl: str, *, dialect: str | None = None) -> Schema:
    """Parse one or more ``CREATE TABLE`` statements into a :class:`Schema`.

    Args:
        ddl: SQL text containing one or more ``CREATE TABLE`` statements.
        dialect: Optional ``sqlglot`` dialect name (e.g. ``"sqlite"``,
            ``"postgres"``). If ``None``, ``sqlglot``'s default parser is used.

    Returns:
        A :class:`Schema` with one :class:`Table` per parsed ``CREATE TABLE``.
        Non-``CREATE TABLE`` statements are ignored.
    """
    schema = Schema()
    for statement in sqlglot.parse(ddl, read=dialect):
        if not isinstance(statement, exp.Create):
            continue
        if (statement.args.get("kind") or "").upper() != "TABLE":
            continue
        table = _parse_create(statement)
        if table is not None:
            schema.tables[table.name] = table
    return schema


def _parse_create(create: exp.Create) -> Table | None:
    """Convert a single ``sqlglot`` ``Create`` expression into a :class:`Table`."""
    table_expr = create.this
    if not isinstance(table_expr, exp.Schema):
        return None
    name = _table_name(table_expr.this)
    if name is None:
        return None

    columns: list[Column] = []
    foreign_keys: list[ForeignKey] = []
    pk_columns: set[str] = set()

    for item in table_expr.expressions:
        if isinstance(item, exp.ColumnDef):
            col, inline_fk = _parse_column(item)
            columns.append(col)
            if col.primary_key:
                pk_columns.add(col.name)
            if inline_fk is not None:
                foreign_keys.append(inline_fk)
        elif isinstance(item, exp.PrimaryKey):
            for col_expr in item.expressions:
                pk_columns.add(_ident(col_expr))
        elif isinstance(item, exp.ForeignKey):
            fk = _parse_table_fk(item)
            if fk is not None:
                foreign_keys.append(fk)

    for col in columns:
        if col.name in pk_columns:
            col.primary_key = True

    return Table(name=name, columns=columns, foreign_keys=foreign_keys)


def _parse_column(col_def: exp.ColumnDef) -> tuple[Column, ForeignKey | None]:
    """Parse a column definition, returning the column and any inline FK."""
    name = _ident(col_def.this)
    type_str = col_def.args.get("kind")
    type_text = type_str.sql(dialect=None) if type_str is not None else ""

    nullable = True
    primary_key = False
    inline_fk: ForeignKey | None = None

    for constraint in col_def.args.get("constraints") or []:
        kind = constraint.args.get("kind")
        if isinstance(kind, exp.PrimaryKeyColumnConstraint):
            primary_key = True
        elif isinstance(kind, exp.NotNullColumnConstraint):
            nullable = False
        elif isinstance(kind, exp.Reference):
            inline_fk = _parse_reference(name, kind)

    return (
        Column(name=name, type=type_text, nullable=nullable, primary_key=primary_key),
        inline_fk,
    )


def _parse_reference(column: str, ref: exp.Reference) -> ForeignKey | None:
    """Parse an inline ``REFERENCES other(col)`` constraint."""
    schema_expr = ref.this
    if isinstance(schema_expr, exp.Schema):
        ref_table = _table_name(schema_expr.this)
        ref_cols = [_ident(e) for e in schema_expr.expressions]
        ref_col = ref_cols[0] if ref_cols else column
    elif isinstance(schema_expr, exp.Table):
        ref_table = _table_name(schema_expr)
        ref_col = column
    else:
        return None
    if ref_table is None:
        return None
    return ForeignKey(column=column, ref_table=ref_table, ref_column=ref_col)


def _parse_table_fk(fk: exp.ForeignKey) -> ForeignKey | None:
    """Parse a table-level ``FOREIGN KEY (...) REFERENCES ...`` constraint."""
    local_cols = [_ident(e) for e in fk.expressions]
    reference = fk.args.get("reference")
    if reference is None or not local_cols:
        return None
    schema_expr = reference.this
    if isinstance(schema_expr, exp.Schema):
        ref_table = _table_name(schema_expr.this)
        ref_cols = [_ident(e) for e in schema_expr.expressions]
    elif isinstance(schema_expr, exp.Table):
        ref_table = _table_name(schema_expr)
        ref_cols = []
    else:
        return None
    if ref_table is None:
        return None
    ref_col = ref_cols[0] if ref_cols else local_cols[0]
    return ForeignKey(column=local_cols[0], ref_table=ref_table, ref_column=ref_col)


def _table_name(node: exp.Expression | None) -> str | None:
    """Extract a bare table name from a ``Table`` or identifier node."""
    if node is None:
        return None
    if isinstance(node, exp.Table):
        return node.name
    if isinstance(node, exp.Identifier):
        return node.this
    return node.name if hasattr(node, "name") else None


def _ident(node: exp.Expression) -> str:
    """Extract an identifier name from a column/identifier node."""
    if isinstance(node, exp.Identifier):
        return node.this
    if isinstance(node, exp.Column):
        return node.name
    return node.name if hasattr(node, "name") else str(node)
