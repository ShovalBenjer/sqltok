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
    """A foreign-key edge from ``local_cols`` to ``ref_table(ref_cols)``.

    Composite keys are first-class: ``local_cols`` and ``ref_cols`` are ordered
    parallel lists (one entry per column in the key), so a multi-column foreign
    key is represented faithfully instead of being truncated to its first column.
    """

    local_cols: list[str]
    ref_table: str
    ref_cols: list[str]


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
            local = ", ".join(fk.local_cols)
            ref = ", ".join(fk.ref_cols)
            body.append(
                f"  FOREIGN KEY ({local}) REFERENCES {fk.ref_table}({ref})"
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

    def fk_edges(self) -> list[tuple[str, ForeignKey]]:
        """Return every resolvable foreign-key edge as ``(source_table, fk)``.

        Only edges whose ``ref_table`` is present in this schema are returned, and
        self-referencing edges are skipped since they add no join connectivity.
        A composite foreign key is a *single* edge here: multi-column keys join
        two tables once, not once per column.
        """
        edges: list[tuple[str, ForeignKey]] = []
        for source, table in self.tables.items():
            for fk in table.foreign_keys:
                if fk.ref_table == source or fk.ref_table not in self.tables:
                    continue
                edges.append((source, fk))
        return edges

    def fk_adjacency(self) -> dict[str, set[str]]:
        """Return the undirected foreign-key adjacency map for the whole schema.

        Built in a single pass over :meth:`fk_edges`, so composite foreign keys
        contribute exactly one undirected edge between the two tables they join.
        """
        adj: dict[str, set[str]] = {name: set() for name in self.tables}
        for source, fk in self.fk_edges():
            adj[source].add(fk.ref_table)
            adj[fk.ref_table].add(source)
        return adj

    def fk_neighbors(self, name: str) -> list[str]:
        """Return tables directly connected to ``name`` by a foreign key.

        This includes both outgoing edges (``name`` references another table) and
        incoming edges (another table references ``name``). A composite foreign
        key yields the referenced table once, not once per column. The result is
        sorted for deterministic ordering.
        """
        if name not in self.tables:
            return []
        neighbors: set[str] = set()
        for source, fk in self.fk_edges():
            if source == name:
                neighbors.add(fk.ref_table)
            elif fk.ref_table == name:
                neighbors.add(source)
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
