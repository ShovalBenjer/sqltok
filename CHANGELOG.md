# Changelog

All notable changes to this project are documented here. The format follows
Keep a Changelog, and the project adheres to Semantic Versioning.

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
