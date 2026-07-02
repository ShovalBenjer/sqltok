# Changelog

All notable changes to this project are documented here. The format follows
Keep a Changelog, and the project adheres to Semantic Versioning.

## [Unreleased]

### Changed

- Coverage selector now spends spare budget on foreign-key neighbours of the
  selected tables (junction tables first), lifting full-recall on BIRD mini-dev
  from 76 to 92 percent at a 1000-token budget and to 97 percent at 2000. New
  `CoverageSelector(fk_min_links=...)` knob trades recall for tokens.

### Added

- `benchmarks/eval_recall.py`: schema-linking recall against BIRD gold SQL, no
  API key required.
- Property-based tests (`tests/test_property.py`, Hypothesis) proving the budget
  invariant, determinism, and validity over arbitrary generated schemas.
- Scale test (`tests/test_scale.py`) on a 500-table synthetic schema.
- `hypothesis` added to the `dev` extra.

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
