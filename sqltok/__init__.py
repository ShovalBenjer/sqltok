"""SQLTok: a Schema Token Budget Manager for Text2SQL agents.

SQLTok retrieves only the most relevant tables/columns for a question within a
configurable token budget and emits a compact ``CREATE TABLE``-style schema
context for an LLM prompt. Token counts are measured with ``tiktoken``; retrieval
is keyword-based BM25 by default with optional hybrid dense retrieval.

Quickstart::

    from sqltok import SchemaBudgetManager

    mgr = SchemaBudgetManager.from_sqlite("path/to/db.sqlite")
    ctx = mgr.build_context("revenue by region last quarter", token_budget=2000)
    print(ctx.text)          # compact schema string for the prompt
    print(ctx.tables)        # selected table names
    print(ctx.token_count)   # measured token count (<= budget)
"""

from __future__ import annotations

from .context import SchemaContext
from .ddl import parse_ddl
from .introspect import introspect_sqlite
from .manager import SchemaBudgetManager
from .models import Column, ForeignKey, Schema, Table
from .retrieval import RankedTable, TableRetriever
from .tokenizer import TokenCounter

__version__ = "0.1.0"

__all__ = [
    "SchemaBudgetManager",
    "SchemaContext",
    "Schema",
    "Table",
    "Column",
    "ForeignKey",
    "TableRetriever",
    "RankedTable",
    "TokenCounter",
    "parse_ddl",
    "introspect_sqlite",
    "__version__",
]
