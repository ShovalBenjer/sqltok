.PHONY: install test lint typecheck check bench-smoke bench-recall build clean

install:
	python -m pip install -e ".[dev]"

test:
	python -m pytest -q

lint:
	ruff check .

typecheck:
	mypy sqltok/

check: lint typecheck test

bench-smoke:
	python benchmarks/make_sample_data.py
	python benchmarks/run_bird.py --provider mock --data-dir benchmarks/sample_data --limit 5

bench-recall:
	python benchmarks/eval_recall.py \
	  --questions benchmarks/data/minidev/MINIDEV/mini_dev_sqlite.json \
	  --db-root  benchmarks/data/minidev/MINIDEV/dev_databases

build:
	python -m build

clean:
	rm -rf dist build *.egg-info .pytest_cache .ruff_cache .mypy_cache .coverage
