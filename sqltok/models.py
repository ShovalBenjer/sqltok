"""Lightweight schema model used throughout SQLTok.

These dataclasses are a deliberately small, dialect-neutral representation of a
relational schema. They are produced either by introspecting a SQLite database
(:func:`sqltok.introspect.introspect_sqlite`) or by parsing DDL
(:func:`sqltok.ddl.parse_ddl`), and they know how to render themselves back to a
compact ``CREATE TABLE``-style string for inclusion in an LLM prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Column:
    """A single column in a table.

    Attributes:
        name: Column name.
        type: SQL type as written in the source DDL (e.g. ``INTEGER``).
        nullable: Whether the column accepts ``NULL``.
        primary_key: Whether the column participates in the primary key.
        description: Optional human-authored description (from a data dictionary).
        sample_values: A handful of example values sampled from the database,
            used to enrich BM25 retrieval. Not rendered into the DDL.
    """

    name: str
    type: str = ""
    nullable: bool = True
    primary_key: bool = False
    description: str | None = None
    sample_values: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ForeignKey:
    """A foreign-key edge from ``column`` to ``ref_table.ref_column``."""

    column: str
    ref_table: str
    ref_column: str


@dataclass(slots=True)
class Table:
    """A table: its columns, foreign keys, and an optional example row.

    Attributes:
        name: Table name.
        columns: Ordered list of :class:`Column`.
        foreign_keys: Outgoing foreign-key edges.
        sample_row: One example row as a ``{column: value}`` mapping, or ``None``.
        description: Optional human-authored table description.
    """

    name: str
    columns: list[Column] = field(default_factory=list)
    foreign_keys: list[ForeignKey] = field(default_factory=list)
    sample_row: dict[str, object] | None = None
    description: str | None = None

    def column_names(self) -> list[str]:
        """Return the ordered list of column names."""
        return [c.name for c in self.columns]

    def render_ddl(self, *, include_sample_row: bool = False) -> str:
        """Render this table as a compact ``CREATE TABLE`` string.

        Args:
            include_sample_row: If ``True`` and a sample row is available, append
                a ``-- example row:`` comment with one example row.

        Returns:
            A multi-line ``CREATE TABLE`` definition. Foreign keys are emitted as
            table-level ``FOREIGN KEY (...) REFERENCES ...`` clauses.
        """
        lines: list[str] = []
        if self.description:
            lines.append(f"-- {self.description}")
        lines.append(f"CREATE TABLE {self.name} (")

        body: list[str] = []
        for col in self.columns:
            parts = [f"  {col.name}"]
            if col.type:
                parts.append(col.type)
            if col.primary_key:
                parts.append("PRIMARY KEY")
            if not col.nullable and not col.primary_key:
                parts.append("NOT NULL")
            line = " ".join(parts)
            if col.description:
                line += f"  -- {col.description}"
            body.append(line)

        for fk in self.foreign_keys:
            body.append(
                f"  FOREIGN KEY ({fk.column}) REFERENCES {fk.ref_table}({fk.ref_column})"
            )

        lines.append(",\n".join(body))
        lines.append(");")

        if include_sample_row and self.sample_row is not None:
            rendered = ", ".join(
                f"{k}={_format_value(v)}" for k, v in self.sample_row.items()
            )
            lines.append(f"-- example row: {rendered}")

        return "\n".join(lines)


@dataclass(slots=True)
class Schema:
    """A collection of tables keyed by name (insertion-ordered)."""

    tables: dict[str, Table] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Normalise to a dict if a list of tables was passed in.
        if isinstance(self.tables, list):  # pragma: no cover - convenience path
            self.tables = {t.name: t for t in self.tables}

    def table_names(self) -> list[str]:
        """Return table names in insertion order."""
        return list(self.tables)

    def get(self, name: str) -> Table | None:
        """Return a table by name, or ``None`` if absent."""
        return self.tables.get(name)

    def fk_neighbors(self, name: str) -> list[str]:
        """Return tables directly connected to ``name`` by a foreign key.

        This includes both outgoing edges (``name`` references another table) and
        incoming edges (another table references ``name``). The result is sorted
        for deterministic ordering.
        """
        neighbors: set[str] = set()
        table = self.tables.get(name)
        if table is not None:
            for fk in table.foreign_keys:
                if fk.ref_table in self.tables:
                    neighbors.add(fk.ref_table)
        for other_name, other in self.tables.items():
            if other_name == name:
                continue
            for fk in other.foreign_keys:
                if fk.ref_table == name:
                    neighbors.add(other_name)
        neighbors.discard(name)
        return sorted(neighbors)

    def render_full_ddl(self, *, include_sample_rows: bool = False) -> str:
        """Render every table's DDL, joined by blank lines (baseline dump)."""
        return "\n\n".join(
            t.render_ddl(include_sample_row=include_sample_rows)
            for t in self.tables.values()
        )


def _format_value(value: object) -> str:
    """Render a sample-row value compactly for a comment line."""
    if value is None:
        return "NULL"
    if isinstance(value, str):
        text = value.replace("\n", " ")
        if len(text) > 40:
            text = text[:37] + "..."
        return f"'{text}'"
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    return str(value)
