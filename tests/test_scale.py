"""Scale test: selection stays correct and terminates on a wide schema.

The value proposition is wide warehouse schemas, so this exercises a synthetic
500-table schema and asserts the budget still holds, selection terminates, and it
is deterministic. The time bound is deliberately loose (measured around 1.5s, the
bound is 30s) so the test is not flaky on slow CI. The measured latency here is
the motivation for the Rust core port; this test guards correctness, not speed.
"""

from __future__ import annotations

import time

from sqltok import Column, ForeignKey, Schema, SchemaBudgetManager, Table
from sqltok.tokenizer import TokenCounter


def _wide_schema(n_tables: int) -> Schema:
    tables: dict[str, Table] = {}
    for i in range(n_tables):
        columns = [
            Column(
                name=f"col{j}",
                type="TEXT",
                sample_values=[f"val_{i}_{j}_{k}" for k in range(3)],
            )
            for j in range(6)
        ]
        columns[0].primary_key = True
        fks = (
            [ForeignKey(column="col1", ref_table=f"t{i - 1}", ref_column="col0")]
            if i > 0
            else []
        )
        tables[f"t{i}"] = Table(name=f"t{i}", columns=columns, foreign_keys=fks)
    return Schema(tables=tables)


def test_wide_schema_respects_budget_and_terminates() -> None:
    schema = _wide_schema(500)
    mgr = SchemaBudgetManager(schema)

    start = time.perf_counter()
    ctx = mgr.build_context("col3 val_10_2_1 col2 t50 val_400_0_0", token_budget=2000)
    elapsed = time.perf_counter() - start

    assert ctx.token_count <= 2000
    assert ctx.token_count == TokenCounter().count(ctx.text)
    assert 0 < len(ctx.tables) <= len(schema.table_names())
    # Very loose ceiling: guards against a runaway, not a performance regression.
    assert elapsed < 30.0


def test_wide_schema_deterministic() -> None:
    schema = _wide_schema(300)
    mgr = SchemaBudgetManager(schema)
    q = "col2 val_7_1_0 t9"
    a = mgr.build_context(q, token_budget=1500)
    b = mgr.build_context(q, token_budget=1500)
    assert a.tables == b.tables
    assert a.token_count == b.token_count
