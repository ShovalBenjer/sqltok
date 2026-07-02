"""Property-based tests: the budget invariant must hold for any input.

Hand-written tests check a handful of cases. These generate arbitrary schemas,
questions, and budgets and assert the load-bearing guarantee: the rendered
context never exceeds the budget, the reported count is honest, and selection is
deterministic. This is the strongest evidence that "never exceeds the budget"
is a property of the code and not of the examples we happened to pick.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from sqltok import (
    Column,
    ForeignKey,
    RelevanceGreedySelector,
    Schema,
    SchemaBudgetManager,
    Table,
)
from sqltok.tokenizer import TokenCounter

_ident = st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=12)
_question = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789 ", min_size=0, max_size=48
)


@st.composite
def schemas(draw: st.DrawFn) -> Schema:
    """Generate a small but arbitrary relational schema."""
    n = draw(st.integers(min_value=1, max_value=6))
    names = draw(st.lists(_ident, min_size=n, max_size=n, unique=True))
    tables: dict[str, Table] = {}
    for name in names:
        col_names = draw(
            st.lists(_ident, min_size=1, max_size=6, unique=True)
        )
        columns = []
        for cn in col_names:
            values = draw(st.lists(st.text(max_size=12), max_size=3))
            columns.append(
                Column(name=cn, type="TEXT", sample_values=[v for v in values if v])
            )
        columns[0].primary_key = True
        tables[name] = Table(name=name, columns=columns)

    # Add a few foreign keys between existing tables.
    for name in names:
        if len(names) > 1 and draw(st.booleans()):
            ref = draw(st.sampled_from(names))
            if ref != name:
                tables[name].foreign_keys.append(
                    ForeignKey(
                        column=tables[name].columns[0].name,
                        ref_table=ref,
                        ref_column=tables[ref].columns[0].name,
                    )
                )
    return Schema(tables=tables)


@settings(max_examples=250, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(schema=schemas(), question=_question, budget=st.integers(min_value=1, max_value=3000))
def test_coverage_budget_never_exceeded(schema: Schema, question: str, budget: int) -> None:
    mgr = SchemaBudgetManager(schema)
    ctx = mgr.build_context(question, token_budget=budget)
    counter = TokenCounter()
    assert ctx.token_count == counter.count(ctx.text)
    assert ctx.token_count <= budget
    # Selected tables are unique and all exist in the schema.
    assert len(ctx.tables) == len(set(ctx.tables))
    assert set(ctx.tables) <= set(schema.table_names())


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(schema=schemas(), question=_question, budget=st.integers(min_value=1, max_value=3000))
def test_relevance_greedy_budget_never_exceeded(
    schema: Schema, question: str, budget: int
) -> None:
    selector = RelevanceGreedySelector(schema)
    ctx = selector.select(question, token_budget=budget, counter=TokenCounter())
    assert ctx.token_count <= budget
    assert set(ctx.tables) <= set(schema.table_names())


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(schema=schemas(), question=_question, budget=st.integers(min_value=1, max_value=3000))
def test_selection_is_deterministic(schema: Schema, question: str, budget: int) -> None:
    mgr = SchemaBudgetManager(schema)
    a = mgr.build_context(question, token_budget=budget)
    b = mgr.build_context(question, token_budget=budget)
    assert a.tables == b.tables
    assert a.text == b.text
    assert a.token_count == b.token_count
