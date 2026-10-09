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
from .ddl import DDLParseError, parse_ddl
from .escalation import (
    DecisionState,
    EscalatedCase,
    EscalationEvidence,
    EscalationPath,
    EscalationPolicy,
    EscalationReport,
    ScoredDecision,
    summarize,
)
from .eval_equivalence import (
    EquivalenceResult,
    EquivalenceVerdict,
    semantic_equivalence,
)
from .eval_governance import (
    ADVERSARIAL_CASES,
    AccessPolicy,
    AdversarialCase,
    BatteryCaseResult,
    BatteryReport,
    GovernanceResult,
    GovernanceVerdict,
    PlanProvider,
    govern,
    resolve_scan_tables,
    run_battery,
)
from .eval_repair import (
    GeneratorFn,
    RepairAttempt,
    RepairLoop,
    RepairMetrics,
    RepairReport,
    repair_metrics,
)
from .eval_retrieval import RetrievalReport, measure_retrieval
from .eval_sandbox import ExecutionOutcome, SandboxExecutor
from .grounding import SchemaGrounding
from .introspect import introspect_sqlite
from .manager import SchemaBudgetManager
from .models import Column, ForeignKey, Schema, Table
from .retrieval import RankedTable, TableRetriever
from .select import (
    AgenticSelector,
    CoverageSelector,
    RelevanceGreedySelector,
    RerankSelector,
    SchemaSelector,
)
from .tokenizer import TokenCounter

__version__ = "0.1.0"

__all__ = [
    "SchemaBudgetManager",
    "SchemaContext",
    "Schema",
    "Table",
    "Column",
    "ForeignKey",
    "SchemaSelector",
    "CoverageSelector",
    "RelevanceGreedySelector",
    "RerankSelector",
    "AgenticSelector",
    "SchemaGrounding",
    "TableRetriever",
    "RankedTable",
    "TokenCounter",
    "parse_ddl",
    "DDLParseError",
    "introspect_sqlite",
    "DecisionState",
    "EscalatedCase",
    "EscalationEvidence",
    "EscalationPath",
    "EscalationPolicy",
    "EscalationReport",
    "ScoredDecision",
    "summarize",
    "SandboxExecutor",
    "ExecutionOutcome",
    "EquivalenceVerdict",
    "EquivalenceResult",
    "semantic_equivalence",
    "RetrievalReport",
    "measure_retrieval",
    "GeneratorFn",
    "RepairAttempt",
    "RepairReport",
    "RepairLoop",
    "RepairMetrics",
    "repair_metrics",
    "AccessPolicy",
    "GovernanceVerdict",
    "GovernanceResult",
    "PlanProvider",
    "govern",
    "resolve_scan_tables",
    "AdversarialCase",
    "ADVERSARIAL_CASES",
    "BatteryCaseResult",
    "BatteryReport",
    "run_battery",
    "__version__",
]
