<div align="center">

<img src="assets/logo.png" alt="SQLTok logo: Text-to-SQL token optimization and schema budget manager for LLM agents" width="300" />

<h1>SQLTok</h1>

<p><b>A schema token budget manager for Text-to-SQL.</b> Given a database and a question, SQLTok selects only the relevant tables and columns within a hard token budget and returns a compact schema string for the prompt.</p>

<p>On BIRD mini-dev (500 questions): keeps <b>97%</b> of gold-query tables at a 2,000-token budget and cuts prompt input <b>36%</b> at 1,000 tokens, benchmarked against BM25. Details in <a href="benchmarks/RESULTS.md">benchmarks/RESULTS.md</a>.</p>

[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/ShovalBenjer/sqltok/actions/workflows/ci.yml/badge.svg)](https://github.com/ShovalBenjer/sqltok/actions/workflows/ci.yml)
[![Linting: Ruff](https://img.shields.io/badge/linting-ruff-261230.svg)](https://github.com/astral-sh/ruff)
[![Typed: mypy](https://img.shields.io/badge/typed-mypy-2a6db2.svg)](https://mypy-lang.org/)

</div>

## Installation

```bash
pip install sqltok
```

Optional extras:

```bash
pip install sqltok[embeddings]   # sentence-transformers for dense retrieval
pip install sqltok[benchmark]    # anthropic, openai clients for live LLM runs
pip install sqltok[dev]          # pytest, hypothesis, ruff, mypy for contributors
```

## Quickstart

```python
from sqltok import SchemaBudgetManager

mgr = SchemaBudgetManager.from_sqlite("path/to/db.sqlite")
ctx = mgr.build_context(
    question="What was the total order amount for customers in France?",
    token_budget=2000,
    include_sample_rows=True,
)

print(ctx.text)          # compact CREATE TABLE schema, at most 2000 tokens
print(ctx.tables)        # ['customers', 'orders']
print(ctx.token_count)   # measured, guaranteed at or below the budget
```

## Features

- **Value grounding**: MinHash + banded LSH over table names, column names, and sampled cell values. Finds mentions that keyword search misses, like "France" in `customers.country`.
- **Submodular budgeting**: Weighted maximum coverage with CELF lazy evaluation, giving a `(1 - 1/e)` approximation guarantee and automatic redundancy removal.
- **FK Steiner connectivity**: Adds the minimal set of bridge tables so the selection is join-connected, preventing hallucinated joins.
- **Hard token budget**: Every candidate is rendered and counted with `tiktoken` before committing. `token_count <= token_budget` is an invariant.
- **Deterministic**: Fixed seeds, no network calls, no model required for selection.
- **Framework-agnostic output**: A plain `CREATE TABLE`-style string that works with every LLM, every framework, and every prompt template.

## How it works

SQLTok turns a schema, a question, and a budget into a budgeted, joinable schema
string in four stages.

1. **Value grounding**: Extract mentions from the question, ground them to tables
   via MinHash + LSH over names and sampled cell values, weight mentions by
   self-supervised IDF.
2. **Submodular budgeting**: Greedily select tables maximizing weighted coverage
   per token, with CELF lazy evaluation and a best-single-table fallback.
3. **FK Steiner connectivity**: Add bridge tables so the selection is
   join-connected.
4. **Budget guarantee**: Re-measure with `tiktoken` at every step; drop sample
   rows before dropping tables.

For a longer, illustrated walkthrough, see the [visual guide](docs/blog/visual-guide-to-sqltok.md).
The canonical Mermaid diagrams are in [`docs/diagrams/`](docs/diagrams/).

## Benchmarks

On BIRD mini-dev (500 questions, 11 SQLite databases), measured with `tiktoken`
(`cl100k_base`). Full details in [`benchmarks/RESULTS.md`](benchmarks/RESULTS.md).

### Schema-linking recall

| budget | table recall | full-recall rate | precision | avg tables |
| ---: | ---: | ---: | ---: | ---: |
| 1000 | 96.3% | 91.8% | 42.8% | 5.45 |
| 2000 | 99.0% | 97.4% | 40.7% | 6.11 |
| 4000 | 99.0% | 97.4% | 39.8% | 6.24 |

### Token reduction

| arm | schema tokens (mean) | total input tokens | total input reduction |
| --- | ---: | ---: | ---: |
| baseline (full dump) | 1161 | 629,819 | reference |
| sqltok at 1000 | 703 | 401,285 | 36.3% |
| sqltok at 2000 | 944 | 521,760 | 17.2% |
| sqltok at 4000 | 1064 | 581,559 | 7.7% |

## Documentation

| Section | Purpose |
| --- | --- |
| [docs/GETTING-STARTED.md](docs/GETTING-STARTED.md) | Installation, first query, common patterns, troubleshooting, real-world SQLite examples. |
| [docs/API.md](docs/API.md) | Full reference for every public class, method, parameter, and data type. |
| [docs/DESIGN.md](docs/DESIGN.md) | Why SQLTok exists, design decisions with alternatives, performance, and the Rust migration path. |
| [docs/blog/visual-guide-to-sqltok.md](docs/blog/visual-guide-to-sqltok.md) | Illustrated walkthrough of the pipeline. |
| [benchmarks/README.md](benchmarks/README.md) | How to run the benchmark harness. |
| [RUNBOOK.md](RUNBOOK.md) | Execution steps: benchmarking, PyPI publishing, docs site deployment, social posting. |

## Contributing

Issues and pull requests are welcome.

```bash
git clone https://github.com/ShovalBenjer/sqltok && cd sqltok
pip install -e ".[dev]"
python -m pytest
ruff check . && mypy sqltok/
```

See [`docs/README.md`](docs/README.md) for the documentation contribution guide.

## Roadmap

1. SID semantic cache for canonicalized query reuse.
2. Intent canonicalizer and invalidation tag registry.
3. Cache backends (Redis, DuckDB).
4. Additional selectors: cross-encoder rerank, LLM agentic discovery.
5. Integrations for LangChain, LlamaIndex, Vanna.
6. Rust core migration for speed and distribution (see [`docs/rust-rewrite-plan.md`](docs/rust-rewrite-plan.md)).

## License

MIT. See [LICENSE](LICENSE).
