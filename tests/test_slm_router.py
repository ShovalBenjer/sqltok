"""Tests for the adaptive SLM schema router (cheap-first, escalate-on-uncertain)."""

from __future__ import annotations

import json

import pytest

from sqltok import SchemaBudgetManager  # noqa: F401  (ensures package import path)
from sqltok.ddl import parse_ddl
from sqltok.select.slm_router import (
    HeuristicFallbackBackend,
    OllamaSLMBackend,
    SLMSchemaRouter,
    _schema_check_ranking,
)
from sqltok.tokenizer import TokenCounter

DDL = """
CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, country TEXT);
CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER, total REAL,
    FOREIGN KEY (customer_id) REFERENCES customers(id));
CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, price REAL);
CREATE TABLE audit_log (id INTEGER PRIMARY KEY, event TEXT, created_at TEXT);
"""


@pytest.fixture()
def schema():
    return parse_ddl(DDL)


@pytest.fixture()
def counter():
    return TokenCounter()


class ScriptedBackend:
    """Deterministic stand-in for an SLM backend."""

    name = "scripted"

    def __init__(self, ranking=None, available=True):
        self._ranking = ranking
        self._available = available
        self.calls = 0

    def available(self):
        return self._available

    def rerank(self, question, candidates, *, table_docs):
        self.calls += 1
        return list(self._ranking) if self._ranking is not None else None


def test_cheap_path_when_bm25_confident(schema, counter):
    backend = ScriptedBackend(ranking=["audit_log"])
    router = SLMSchemaRouter(schema, backend=backend)
    ctx = router.select("show me all customers", token_budget=2000, counter=counter)
    assert ctx.token_count <= 2000
    assert router.decisions[-1]["path"] == "cheap"
    assert router.decisions[-1]["backend"] == "bm25"
    assert backend.calls == 0  # confident -> no SLM call at all
    assert "customers" in ctx.tables


def test_escalates_when_bm25_uncertain(schema, counter):
    # 'name' ties customers.name and products.name -> BM25 margin is 0.
    backend = ScriptedBackend(ranking=["orders", "customers", "products", "audit_log"])
    router = SLMSchemaRouter(schema, backend=backend)
    ctx = router.select("name", token_budget=2000, counter=counter)
    assert backend.calls == 1
    assert router.decisions[-1]["path"] == "escalated"
    assert router.decisions[-1]["backend"] == "scripted"
    assert ctx.tables[0] == "orders"


def test_backend_decline_falls_back_to_heuristic(schema, counter):
    primary = ScriptedBackend(ranking=None)  # declines
    router = SLMSchemaRouter(schema, backend=primary)
    # 'revenue' matches nothing in BM25 (all zeros -> uncertain); the heuristic
    # synonym map (revenue -> total/amount/price) recovers orders/products.
    ctx = router.select("revenue", token_budget=2000, counter=counter)
    assert router.decisions[-1]["path"] == "escalated"
    assert router.decisions[-1]["backend"] == "heuristic"
    # heuristic synonym expansion (revenue -> total/amount/price) must surface
    # the money tables above the irrelevant ones
    assert set(ctx.tables[:2]) == {"orders", "products"}


def test_all_backends_down_falls_back_to_bm25(schema, counter):
    primary = ScriptedBackend(ranking=["orders"], available=False)
    fallback = ScriptedBackend(ranking=None, available=False)
    router = SLMSchemaRouter(schema, backend=primary, fallback=fallback)
    router.select("name", token_budget=2000, counter=counter)
    assert router.decisions[-1]["path"] == "fallback_bm25"


def test_decision_log_hides_question_text(schema, counter):
    router = SLMSchemaRouter(schema)
    router.select("show me all customers", token_budget=2000, counter=counter)
    record = router.decisions[-1]
    assert "question_sha256" in record
    assert "show me all customers" not in json.dumps(record)


def test_schema_check_accepts_valid_ranking():
    out = _schema_check_ranking({"tables": ["b", "a"]}, ["a", "b", "c"])
    assert out == ["b", "a", "c"]  # omitted candidates appended in BM25 order


def test_schema_check_rejects_hallucinated_table():
    assert _schema_check_ranking({"tables": ["b", "nope"]}, ["a", "b"]) is None


def test_schema_check_rejects_non_json_shape():
    assert _schema_check_ranking(["a", "b"], ["a", "b"]) is None
    assert _schema_check_ranking({"tables": []}, ["a", "b"]) is None
    assert _schema_check_ranking({"other": 1}, ["a", "b"]) is None


def test_schema_check_dedupes():
    assert _schema_check_ranking({"tables": ["a", "a", "b"]}, ["a", "b"]) == ["a", "b"]


def test_heuristic_backend_is_deterministic_and_safe():
    backend = HeuristicFallbackBackend()
    assert backend.available()
    docs = {"orders": "orders customer_id total", "audit_log": "audit_log event"}
    first = backend.rerank("revenue", ["orders", "audit_log"], table_docs=docs)
    second = backend.rerank("revenue", ["orders", "audit_log"], table_docs=docs)
    assert first == second
    assert set(first) == {"orders", "audit_log"}  # never invents names
    assert first[0] == "orders"  # revenue -> total synonym


def test_ollama_backend_unavailable_without_server(monkeypatch):
    import urllib.error

    def boom(req, timeout=None):
        raise urllib.error.URLError("nope")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    backend = OllamaSLMBackend(model="tiny", host="http://127.0.0.1:9")
    assert not backend.available()
    assert backend.rerank("q", ["a"], table_docs={"a": "doc"}) is None


def test_ollama_backend_schema_checks_response(monkeypatch):

    class FakeResp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"message": {"content": '{"tables": ["evil_table"]}'}}).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: FakeResp())
    backend = OllamaSLMBackend(model="tiny")
    backend._reachable = True
    # 'evil_table' is not a candidate -> decline, don't hallucinate
    assert backend.rerank("q", ["a", "b"], table_docs={"a": "", "b": ""}) is None


def test_budget_and_fk_expansion_respected(schema, counter):
    backend = ScriptedBackend(ranking=["orders", "customers", "products", "audit_log"])
    router = SLMSchemaRouter(schema, backend=backend)
    ctx = router.select("name", token_budget=500, counter=counter, fk_expand=True)
    assert ctx.token_count <= 500
    # orders references customers -> FK expansion should pull it in if budget allows
    assert "orders" in ctx.tables
