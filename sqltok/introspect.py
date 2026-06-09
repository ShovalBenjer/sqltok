"""Introspect a SQLite database into the SQLTok schema model.

Reads table/column metadata via ``PRAGMA`` statements and samples a few rows per
table so retrieval has real column values and one example row per table is
available for the prompt. No data leaves the process; this is purely local I/O.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import Column, ForeignKey, Schema, Table


def introspect_sqlite(
    db_path: str | Path,
    *,
    sample_rows: int = 3,
    max_sample_values: int = 5,
) -> Schema:
    """Build a :class:`Schema` from a SQLite database file.

    Args:
        db_path: Path to a ``.sqlite``/``.db`` file.
        sample_rows: Number of rows to sample per table (the first row becomes
            the table's example row; all sampled rows feed retrieval values).
        max_sample_values: Max distinct sample values kept per column.

    Returns:
        A :class:`Schema` describing every user table (``sqlite_*`` tables are
        skipped).
    """
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"SQLite database not found: {path}")

    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        schema = Schema()
        for table_name in _list_tables(conn):
            table = _introspect_table(
                conn,
                table_name,
                sample_rows=sample_rows,
                max_sample_values=max_sample_values,
            )
            schema.tables[table_name] = table
        return schema
    finally:
        conn.close()


def _list_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [r["name"] for r in rows]


def _introspect_table(
    conn: sqlite3.Connection,
    name: str,
    *,
    sample_rows: int,
    max_sample_values: int,
) -> Table:
    info = conn.execute(f'PRAGMA table_info("{name}")').fetchall()
    columns = [
        Column(
            name=row["name"],
            type=(row["type"] or "").strip(),
            nullable=not row["notnull"],
            primary_key=bool(row["pk"]),
        )
        for row in info
    ]

    foreign_keys: list[ForeignKey] = []
    for fk in conn.execute(f'PRAGMA foreign_key_list("{name}")').fetchall():
        foreign_keys.append(
            ForeignKey(
                column=fk["from"],
                ref_table=fk["table"],
                ref_column=fk["to"] or fk["from"],
            )
        )

    sample_row, value_map = _sample(conn, name, columns, sample_rows, max_sample_values)
    for col in columns:
        col.sample_values = value_map.get(col.name, [])

    return Table(
        name=name,
        columns=columns,
        foreign_keys=foreign_keys,
        sample_row=sample_row,
    )


def _sample(
    conn: sqlite3.Connection,
    name: str,
    columns: list[Column],
    sample_rows: int,
    max_sample_values: int,
) -> tuple[dict[str, object] | None, dict[str, list[str]]]:
    if sample_rows <= 0 or not columns:
        return None, {}
    try:
        rows = conn.execute(
            f'SELECT * FROM "{name}" LIMIT {int(sample_rows)}'
        ).fetchall()
    except sqlite3.Error:
        return None, {}
    if not rows:
        return None, {}

    sample_row = {key: rows[0][key] for key in rows[0].keys()}

    value_map: dict[str, list[str]] = {}
    for col in columns:
        seen: list[str] = []
        for row in rows:
            value = row[col.name]
            if value is None:
                continue
            text = str(value).strip()
            if text and text not in seen:
                seen.append(text)
            if len(seen) >= max_sample_values:
                break
        value_map[col.name] = seen
    return sample_row, value_map
