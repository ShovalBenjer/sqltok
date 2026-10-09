# REVIEW.md — judging policy for reviewers (human and bot)

Read this when judging a change. For how to build here, see AGENTS.md.

## Severity calibration

- **Blocking.** Weakened or removed oracles: property/fuzz tests
  (`tests/test_property.py`, `tests/test_fuzz_ddl.py`), schema-budget invariants
  (`tests/test_budget.py`), or anything that lets an unbudgeted or mis-tokenized
  schema reach the model. Security findings (injection, secret leaks, dependency
  CVEs). Data corruption or non-append-only mutation of an append-only ledger.
- **Advisory.** Style nits, docstring wording, anything ruff would not flag.
- **Nit is never blocking.** If it is not worth a re-review round, say so inline
  and approve.

A PR that weakens an oracle — deletes or skips a property test, lowers the
coverage gate — is a blocking finding regardless of diff size.

## Paths to skip (generated — never comment on style)

- `benchmarks/sample_data/**`, `benchmarks/results/**` — fixtures and outputs.
- `uv.lock` — generated lockfile; comment only on direct-dependency changes.
- `demo/` — throwaway demo app, not shipped code.

## Verification expected

A change touching `sqltok/` or `tests/` must show, matching
`.github/workflows/ci.yml`:

```
ruff check .
ruff format --check .
mypy sqltok/ --strict
pytest --cov=sqltok --cov-fail-under=80
```

## Summary style

Lead with the verdict (approve / request changes / comment), then blocking
findings first, with `file:line` references. Do not restate the diff.

## Sub-agent budget

- Small diffs (<200 lines): no sub-agents; read the diff directly.
- Large diffs: at most one focused sub-task (e.g. verify a single invariant);
  never re-review the whole PR in parallel.
