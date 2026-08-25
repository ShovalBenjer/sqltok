# Contributing

Thank you for your interest in contributing to SQLTok. This document covers the
developer setup, local workflow, and pull request guidelines.

## Developer Setup

Clone the repository and install the package with its development extras:

```bash
git clone https://github.com/ShovalBenjer/sqltok && cd sqltok
python -m pip install -e ".[dev]"
```

The `dev` extra installs `pytest`, `pytest-cov`, `hypothesis`, `ruff`, and `mypy`.

Optional benchmarks and providers use additional extras (`benchmark`, `embeddings`);
see `pyproject.toml` for the full list.

## Running Tests

Run the test suite (no API keys are required; tests are fully local):

```bash
python -m pytest
```

Coverage is enforced at 80 percent in CI. To check coverage locally:

```bash
pytest --cov=sqltok --cov-report=term --cov-fail-under=80
```

A convenience Makefile is provided:

```bash
make install       # install package + dev extras
make check         # run lint, typecheck (mypy sqltok/), and tests
make bench-smoke   # run the mock-LLM benchmark smoke test
```

## Linting and Type Checking

```bash
ruff check .
ruff format --check .
mypy sqltok/ --strict
```

The same checks run in CI. Pre-commit hooks (`ruff`, `ruff-format`, `mypy`) mirror
these commands; install and run them with:

```bash
pip install pre-commit
pre-commit install
pre-commit run --all-files
```

## Pull Request Guidelines

- Keep changes focused. One logical change per PR.
- Add tests for any new behavior or bug fix. All existing tests must pass.
- Run the full check suite (`ruff`, `mypy --strict`, `pytest --cov`) locally before
  opening a PR.
- Run `ruff format .` if formatting checks fail locally.
- Update documentation when the public API changes.
- Follow the existing code style. Type hints are required for all public functions
  and methods.
- Write a clear PR description explaining the motivation and approach.

## Code of Conduct

Be respectful and constructive. SQLTok is a research-oriented library and we welcome
questions, bug reports, and improvements from all contributors.
