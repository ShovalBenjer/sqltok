"""Tests for retrieval ranking and its determinism."""

from __future__ import annotations

from sqltok import SchemaBudgetManager, parse_ddl
from sqltok.retrieval import TableRetriever


def test_ranking_is_deterministic(sample_ddl: str) -> None:
    schema = parse_ddl(sample_ddl)
    retriever = TableRetriever(schema)
    q = "total order amount by product category"
    first = [r.name for r in retriever.rank(q)]
    for _ in range(5):
        assert [r.name for r in retriever.rank(q)] == first


def test_ranking_returns_all_tables(sample_ddl: str) -> None:
    schema = parse_ddl(sample_ddl)
    retriever = TableRetriever(schema)
    ranked = retriever.rank("orders")
    assert sorted(r.name for r in ranked) == sorted(schema.table_names())


def test_no_match_falls_back_to_alphabetical(sample_ddl: str) -> None:
    schema = parse_ddl(sample_ddl)
    retriever = TableRetriever(schema)
    ranked = retriever.rank("zzzqqq nonexistent token")
    # All scores zero -> deterministic alphabetical tie-break.
    assert all(r.score == 0.0 for r in ranked)
    assert [r.name for r in ranked] == sorted(schema.table_names())


def test_relevant_table_outranks_irrelevant(sample_ddl: str) -> None:
    schema = parse_ddl(sample_ddl)
    retriever = TableRetriever(schema)
    ranked = retriever.rank("supplier company country")
    assert ranked[0].name == "suppliers"


def test_build_context_is_deterministic(sample_ddl: str) -> None:
    mgr = SchemaBudgetManager.from_ddl(sample_ddl)
    q = "order amount by region"
    a = mgr.build_context(q, token_budget=300)
    b = mgr.build_context(q, token_budget=300)
    assert a.text == b.text
    assert a.tables == b.tables
    assert a.token_count == b.token_count
