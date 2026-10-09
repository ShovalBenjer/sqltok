# Changelog

All notable changes to this project are documented here. The format follows
Keep a Changelog, and the project adheres to Semantic Versioning.

## [Unreleased]

### Added

- Execution-grounded Text2SQL evaluation battery (issue #43): syntax-valid SQL
  is not semantically-correct SQL, so generated queries are now evaluated by
  *running* them. New modules `sqltok/eval_sandbox.py` (`SandboxExecutor`:
  read-only SQLite execution with a VM-operation budget, failures captured as
  `ExecutionOutcome` never raised, `EXPLAIN QUERY PLAN` full-scan signal),
  `sqltok/eval_equivalence.py` (`semantic_equivalence`: generated-vs-reference
  result comparison, `EQUIVALENT`/`ROW_COUNT_MISMATCH`/`ROW_CONTENT_MISMATCH`/
  `EXECUTION_ERROR`/`GOLD_ERROR`), `sqltok/eval_retrieval.py`
  (`measure_retrieval`: recall, precision, full-recall, FK-edge coverage,
  latency — the under/over-retrieval distinction), `sqltok/eval_repair.py`
  (`RepairLoop`: generate → execute → error-feedback retry, exhaustion falls
  back to a declared `EscalationPolicy` with unhandled failures recorded as
  their own metric; `repair_metrics` aggregation), `sqltok/eval_governance.py`
  (`AccessPolicy` declared in advance like `EscalationPolicy`, `govern`
  fail-closed: unparseable/multi-statement/unsafe/restricted-table/
  expensive-scan blocks, `run_battery` pinning 11 adversarial cases).
  `benchmarks/eval_execution.py` runs the whole battery offline on the sample
  fixture with the mock LLM (see `benchmarks/RESULTS.md` for measured
  numbers). 42 adversarial tests in `tests/test_eval_grounded.py`, including
  the chapter's canonical executes-fine-but-wrong query. Named gap:
  entity-grounding precision needs annotated question entities the fixtures
  do not carry, so it is not faked.

- Escalation protocol with first-class states (issue #38): escalation-to-human
  is now a designed branch of the selection protocol, not a failure mode. New
  `sqltok/escalation.py` declares `DecisionState` (`SERVED`/`ESCALATED`, a
  closed enum with no failure member), `EscalationPath` (`no_grounding`,
  `budget_exhausted`, `low_coverage`, `ambiguous_grounding`),
  `EscalationPolicy` (paths declared in advance with validated thresholds and
  arbiter; only declared paths can fire, declaration order is priority), and
  `summarize`/`EscalationReport` (automated score statistics over `SERVED`
  cases only — escalated cases are excluded by construction — with escalation
  reported as normal routing telemetry, never as failure).
  `SchemaBudgetManager.build_context(..., escalation_policy=...)` evaluates the
  built context against the declared paths and stamps escalated contexts with
  their `EscalatedCase`; without a policy behaviour is unchanged.
  `SchemaContext` carries `decision_state`/`escalation` plus grounding
  evidence (`grounded_mentions`, `top_scores`, `coverage_reported`), guarded by
  a fail-closed `__post_init__` invariant. 26 adversarial tests in
  `tests/test_escalation.py`.

### Changed

- Coverage selector now spends spare budget on foreign-key neighbours of the
  selected tables (junction tables first), lifting full-recall on BIRD mini-dev
  from 76 to 92 percent at a 1000-token budget and to 97 percent at 2000. New
  `CoverageSelector(fk_min_links=...)` knob trades recall for tokens.

### Added

- `benchmarks/eval_recall.py`: schema-linking recall against BIRD gold SQL, no
  API key required.
- Keyless local benchmark provider (`--provider ollama`) so execution accuracy
  can be scored with no OpenAI or Anthropic key.
- `DDLParseError` (a `ValueError` subclass): `parse_ddl` now raises this instead
  of leaking sqlglot's exception type.
- Test pyramid additions: property-based (`tests/test_property.py`), statistical
  (`tests/test_statistical.py`), fuzz/chaos on the DDL parser
  (`tests/test_fuzz_ddl.py`), regression snapshots (`tests/test_regression.py`),
  and a 500-table scale test (`tests/test_scale.py`). 61 tests total.
- `hypothesis` added to the `dev` extra. `Makefile` and `RUNBOOK.md` for common
  tasks and the release path.

### Fixed

- `TableRetriever` no longer crashes on a degenerate corpus where every name
  tokenises to nothing (empty BM25 vocabulary); it falls back to a name-ordered
  ranking. NaN BM25 scores from empty documents are treated as zero. Found by the
  property-based tests.

## [0.1.0] - 2026-06-10

First public release: the schema token budget manager and a BIRD benchmark
harness.

### Added

- `SchemaBudgetManager` public API, built from a SQLite database
  (`from_sqlite`) or from DDL (`from_ddl`).
- `CoverageSelector`, the default value-grounded submodular selector:
  - native MinHash and banded LSH value grounding over sampled cell values;
  - self-supervised IDF mention weights learned from the schema;
  - token-budgeted CELF lazy greedy with a Khuller-Moss-Naor single-table
    comparison;
  - foreign-key Steiner connectivity to keep the selection joinable.
- `RelevanceGreedySelector`, a BM25 baseline for ablation.
- `SchemaSelector` protocol, plus typed `RerankSelector` and `AgenticSelector`
  stubs for the v0.2 roadmap.
- Real token counting with `tiktoken`; the returned context never exceeds the
  budget.
- `sqlglot` DDL parsing and SQLite introspection with cell-value sampling.
- BIRD mini-dev benchmark harness with baseline and SQLTok arms, resumable
  on-disk response caching, Anthropic, OpenAI, and mock clients, and BIRD-format
  predictions for the official execution-accuracy script.
- Test suite (no API keys required), `ruff` and `mypy` configuration, and CI on
  Python 3.11 and 3.12.

[0.1.0]: https://github.com/ShovalBenjer/sqltok/releases/tag/v0.1.0
