"""Fuzz / chaos tests for the DDL parser.

The parser must never crash with an unexpected exception on arbitrary input. Its
contract is: return a Schema, or raise DDLParseError. Anything else (a
TypeError, AttributeError, IndexError, and so on) is a bug. Hypothesis throws
random text and near-miss DDL at it to enforce that.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from sqltok import DDLParseError, Schema, parse_ddl

# A mix of free text and DDL-shaped fragments, to land near the parser's edges.
_fragments = st.one_of(
    st.text(max_size=60),
    st.sampled_from(
        [
            "CREATE TABLE",
            "CREATE TABLE t",
            "CREATE TABLE t (",
            "CREATE TABLE t ()",
            "CREATE TABLE t (a INT,)",
            "CREATE TABLE t (a INT REFERENCES x)",
            "FOREIGN KEY",
            "PRIMARY KEY (a)",
            ");",
            "CREATE TABLE t (a INT PRIMARY KEY, b TEXT NOT NULL)",
        ]
    ),
)
_ddl = st.lists(_fragments, max_size=5).map(lambda parts: " ".join(parts))


@settings(max_examples=400, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(ddl=_ddl)
def test_parse_ddl_never_crashes(ddl: str) -> None:
    try:
        schema = parse_ddl(ddl)
    except DDLParseError:
        return  # the one allowed failure mode
    assert isinstance(schema, Schema)
    # Any table produced must be internally consistent.
    for name, table in schema.tables.items():
        assert table.name == name
        assert len(table.column_names()) == len(set(table.column_names()))


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(ddl=_ddl)
def test_parse_ddl_result_is_renderable(ddl: str) -> None:
    try:
        schema = parse_ddl(ddl)
    except DDLParseError:
        return
    # Whatever parsed must render without error (feeds the prompt path).
    text = schema.render_full_ddl(include_sample_rows=False)
    assert isinstance(text, str)
