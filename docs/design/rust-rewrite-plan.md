# SQLTok Rust rewrite and maturity plan

## Recommendation up front

Do not big-bang rewrite. Port the hot, well-specified core to a Rust crate and
expose it through the existing `pip install sqltok` API with a PyO3 wheel, while
keeping the current Python implementation as the oracle until parity is proven on
BIRD. Keep the LLM and benchmark glue in Python. This preserves the working v0.1
and its audience, puts Rust where it actually helps, and de-risks the move with
differential testing.

The default plan below is the hybrid Rust core. A pure-Rust variant and a
Rust-CLI-only variant are noted where they differ.

## What Rust buys, and what it does not

Buys:
- Speed on the selection and grounding loop, which is the part that must scale to
  wide warehouse schemas with thousands of tables.
- Single static binary distribution and a real crate for the Rust data ecosystem
  (DataFusion, Polars, sqlparser are all Rust).
- Memory safety and fearless concurrency for batch and serving use.

Does not buy:
- Better recall or accuracy. Those are algorithmic and live in the design, not
  the language. The recent jump from 78 to 97 percent full-recall came from the
  FK-expansion algorithm, not from any language feature.
- Any benefit for the LLM clients or the BIRD harness. Those stay in Python.

## Module port map and risk

| Python module | Rust target | Crate | Risk |
| --- | --- | --- | --- |
| `tokenizer.py` (tiktoken) | token counting | `tiktoken-rs` | low |
| `grounding/minhash.py` | MinHash | native, `wyhash` or `ahash` | low, large speedup |
| `grounding/lsh.py` | banded LSH | native, bitpacked bands | low |
| `grounding/text.py` | mentions, shingles | native, `regex` | low |
| `grounding/affinity.py` | cover matrix, IDF | native, `ndarray` or `Vec` | low |
| `select/coverage.py` | submodular CELF greedy | native, `BinaryHeap` | medium |
| `select/connect.py` | FK Steiner, BFS | native, `petgraph` | low |
| `select/base.py` budget packer | budget loop | native | low |
| `models.py`, `context.py` | structs | native, `serde` | low |
| `retrieval.py` (bm25s) | BM25 baseline | native | low |
| `introspect.py` (sqlite3) | introspection | `rusqlite` | low |
| `ddl.py` (sqlglot) | DDL parse, FK extract | `sqlparser-rs` | high |
| `benchmarks/`, `llm/` | harness, clients | stay in Python | n/a |

The single long pole is the DDL parser. `sqlglot` is multi-dialect with a rich
AST and our FK and constraint extraction relies on it. `sqlparser-rs` is mature
and used by DataFusion and Polars, but it has a different AST and different
dialect coverage. Mitigation: start with SQLite and ANSI, differential-test the
extracted schema (tables, columns, PKs, FKs) against the sqlglot output on every
BIRD database, and keep the Python parser available as a fallback during the
transition.

## Mature SQL practices (the SQL thread)

- Dialect-aware parsing with explicit dialects (SQLite, Postgres, MySQL,
  Snowflake) rather than one permissive parser, with correct identifier quoting
  and case-folding rules per dialect.
- Catalog-based introspection: `information_schema` for Postgres and MySQL via
  `sqlx` or `tokio-postgres`, `PRAGMA` for SQLite via `rusqlite`. Today only
  SQLite is supported.
- Handle composite foreign keys, views, generated columns, and column comments
  and descriptions pulled from the catalog, none of which v0.1 handles.
- Type-aware value sampling: reservoir sampling or `TABLESAMPLE` where available,
  explicit NULL handling, and large-value truncation, instead of the current
  first-three-rows sample that leaves 17 percent of columns with no values.
- Deterministic, dialect-correct DDL rendering for the prompt.
- Optional: align the schema types with DataFusion catalog traits so SQLTok can
  plug into the Rust SQL ecosystem.

## Mature coding practices

- Cargo workspace: `sqltok-core` (library), `sqltok-cli` (binary), `sqltok-py`
  (PyO3 bindings, built with maturin), `sqltok-bench`.
- Errors with `thiserror` in libraries and `anyhow` in binaries. No `unwrap` or
  `panic` in library code. `#[non_exhaustive]` on public enums.
- API design with a builder for the manager, typed budgets, and semver
  discipline with a documented MSRV.
- Test pyramid:
  - unit tests per module.
  - `proptest` for the invariants: budget never exceeded for any generated
    schema, question, and budget; coverage objective monotone and submodular.
  - `criterion` microbenchmarks for grounding and selection.
  - `cargo-fuzz` on the DDL parser.
  - differential tests against the Python oracle: identical selected-table sets
    on all 500 BIRD questions, or documented and justified diffs.
  - `insta` snapshot tests for rendered DDL.
  - `miri` if any `unsafe` appears (target is none).
- CI: `clippy -D warnings`, `rustfmt --check`, `cargo test`, `cargo deny` for
  licenses and advisories, coverage via `cargo-llvm-cov`, wheels via maturin and
  `cibuildwheel` for manylinux, macOS, and Windows, and docs on docs.rs.

## Phased migration

- Phase 0, spike (1 to 2 days). `tiktoken-rs` plus MinHash, LSH, and the coverage
  loop on one BIRD database. Prove the speedup and identical selection on a
  sample. Throwaway code, decision gate.
- Phase 1, core crate (1 to 2 weeks). `sqltok-core` with grounding, coverage,
  connect, and budget, SQLite introspection via `rusqlite`, and DDL via
  `sqlparser-rs` for SQLite and ANSI. Differential-test against Python on all 500
  BIRD questions and require parity on selected tables before proceeding.
- Phase 2, Python wheel (1 week). `sqltok-py` exposes `SchemaBudgetManager` with
  the same signatures. Swap the Python internals to call Rust, keep all existing
  Python tests green, ship as the same `sqltok` package so users see no API change.
- Phase 3, reach (1 to 2 weeks). `sqltok-cli` binary, Postgres and MySQL
  introspection, more dialects.
- Phase 4, cleanup. Retire the pure-Python core, keep the Python benchmark and
  LLM layer calling the Rust core.

Pure-Rust variant: skip Phase 2, ship only the crate and CLI. Loses the Python
audience, so not recommended unless the target users are Rust services.

## Validation and safety

Differential testing is the spine. The current Python implementation is the
oracle. No swap happens until the Rust core produces the same selected tables and
the same token counts on BIRD, within a documented tolerance. The Python package
keeps working throughout, and the Rust core ships only when it is at parity.

## When not to do this

- If the next goal is accuracy or features (the SID cache, derivations,
  framework integrations), Rust does not help. Build those in Python first.
- Do not port the LLM clients or the BIRD harness to Rust.
- Do not start before the keyed execution-accuracy number exists, so we are
  optimizing something we have proven works.

## Rough effort

Phase 0 to Phase 2 is about three to four weeks of focused work, with the DDL
parser parity as the dominant risk and cost. Phase 3 adds one to two weeks per
additional database backend.
