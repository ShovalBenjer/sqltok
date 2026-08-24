# Contributing

Thank you for your interest in contributing to SQLTok. This document covers the developer workflow, test commands, and pull request guidelines.

## Developer Setup

Clone the repository and install the package with development extras:

```bash
git clone https://github.com/ShovalBenjer/sqltok && cd sqltok
python -m pip install -e ".[dev]"
```

The `dev` extra installs `pytest`, `hypothesis`, `ruff`, and `mypy`.

## Running Tests

```bash
python -m pytest
```

Coverage is enforced at 80 percent in CI. To check coverage locally:

```bash
pytest --cov=sqltok --cov-report=term
```

## Linting and Type Checking

```bash
ruff check .
ruff format --check .
mypy sqltok/ --strict
```

## Pull Request Guidelines

- Keep changes focused and small. One logical change per PR.
- Add tests for any new behavior or bug fix. All existing tests must pass.
- Run the full check suite (`ruff`, `mypy --strict`, `pytest`) locally before opening a PR.
- Update documentation when the public API changes.
- Follow the existing code style. Python type hints are required for all public functions and methods.
- Write a clear PR description explaining the motivation and approach.

## Code of Conduct

Be respectful and constructive. SQLTok is a research-oriented library and we welcome questions, bug reports, and improvements from all contributors.
