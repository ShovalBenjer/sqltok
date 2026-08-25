# SQLTok Documentation

## Documentation hierarchy

This directory contains the complete SQLTok documentation. Each section has a
specific audience and purpose.

| Section | Audience | Purpose |
| --- | --- | --- |
| [`README.md`](../README.md) | Everyone | Project overview, install, quickstart, benchmark results, contribution guide. |
| [`GETTING-STARTED.md`](GETTING-STARTED.md) | New users | Step-by-step guide to installation, first query, common patterns, troubleshooting, and benchmark setup. |
| [`API.md`](API.md) | Developers | Full reference for every public class, method, parameter, and data type, with examples and performance notes. |
| [`DESIGN.md`](DESIGN.md) | Researchers and contributors | Why SQLTok exists, how it fits in the SQL tooling ecosystem, design decisions with alternatives considered, performance characteristics, and the Rust migration path. |
| [`blog/visual-guide-to-sqltok.md`](blog/visual-guide-to-sqltok.md) | Curious readers | Illustrated walkthrough of the pipeline with Mermaid diagrams. This is a thin pointer to the canonical diagrams below. |
| [`diagrams/`](diagrams/) | All audiences | Single source of truth for all architecture diagrams, written in Mermaid. |

## Audience summary

- **First-time users** should start with [`GETTING-STARTED.md`](GETTING-STARTED.md),
  then skim the benchmark numbers in [`../README.md`](../README.md).
- **Integrators** who are wiring SQLTok into a Text-to-SQL pipeline should read
  [`API.md`](API.md) for the full public surface and [`DESIGN.md`](DESIGN.md) for
  the guarantees the library provides.
- **Contributors** should read [`DESIGN.md`](DESIGN.md) for design rationale,
  [`API.md`](API.md) for the selector protocol, and
  [`RUNBOOK.md`](../RUNBOOK.md) for the execution steps (benchmarking, publishing,
  docs site deployment, social posting).

## How to contribute to docs

Documentation lives in the same repository as the code. To update it:

1. Fork and clone the repo.
2. Install dev dependencies: `pip install -e ".[dev]"`.
3. Make your changes in the `docs/` directory.
4. Run the checks: `ruff check docs/ && mypy sqltok/`.
5. Run the tests: `python -m pytest`.
6. Open a pull request with a clear description of what changed and why.

Every document in `docs/` must be standalone and comprehensive. Do not create
thin pointers or placeholder stubs. If a section is referenced from another
document, it should contain the full content, not just a link.

## Reference: execution runbook

For the steps that ship SQLTok to users — running the BIRD benchmark, publishing
to PyPI, deploying the docs site, and social posting — see [`../RUNBOOK.md`](../RUNBOOK.md).

The benchmark harness is documented in [`../benchmarks/README.md`](../benchmarks/README.md).
The benchmark results are maintained in [`../benchmarks/RESULTS.md`](../benchmarks/RESULTS.md).
