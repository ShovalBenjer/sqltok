# Getting Started with SQLTok

## Prerequisites

SQLTok requires Python 3.11 or later and has no hard runtime dependencies beyond
the core scientific stack. All token counting uses `tiktoken` (`cl100k_base` by
default), and the default selector uses BM25 via `bm25s` and MinHash/LSH via
`numpy` and pure Python.

```bash
python --version   # 3.11 or later
```

## Installation

Install from PyPI:

```bash
pip install sqltok
```

Optional extras:

```bash
pip install sqltok[embeddings]   # sentence-transformers for dense retrieval
pip install sqltok[benchmark]    # anthropic, openai clients for live LLM runs
pip install sqltok[dev]          # pytest, hypothesis, ruff, mypy for contributors
```

Verify the install:

```bash
python -c "import sqltok; print(sqltok.__version__)"
# 0.1.0
```

## First query

The fastest path to a result is to point SQLTok at a SQLite database and ask a
question.

```python
from sqltok import SchemaBudgetManager

# Build from a live SQLite file.
mgr = SchemaBudgetManager.from_sqlite("path/to/db.sqlite")

# Build a token-budgeted schema context for your question.
ctx = mgr.build_context(
    question="What was the total order amount for customers in France?",
    token_budget=2000,
    include_sample_rows=True,
)

print(ctx.text)
# compact CREATE TABLE schema string, at most 2000 tokens

print(ctx.tables)
# ['customers', 'orders']

print(ctx.token_count)
# measured, guaranteed at or below the budget

print(ctx.bridge_tables)
# []  (foreign-key bridges added to keep the schema joinable)

print(ctx.covered_weight)
# 0.85  (fraction of grounded question mentions covered)
```

The returned `ctx.text` is a compact `CREATE TABLE`-style string ready to drop
into an LLM prompt. Token counts are measured with `tiktoken`, not estimated, so
the `token_count` is a hard invariant.

### First query with raw DDL

If you do not have a live database, you can build a manager from DDL text:

```python
from sqltok import SchemaBudgetManager

ddl = """
CREATE TABLE customers (
  customer_id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  country TEXT
);

CREATE TABLE orders (
  order_id INTEGER PRIMARY KEY,
  customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
  order_date TEXT,
  total REAL
);
"""

mgr = SchemaBudgetManager.from_ddl(ddl)
ctx = mgr.build_context("total orders for customers in France", token_budget=2000)
print(ctx.text)
```

## Common patterns

### Choosing a token budget

The budget is a hard ceiling on the schema context tokens. Pick it based on the
model context window and how much room you need for the question, system prompt,
and the model's SQL answer.

| Budget | Typical use case |
| ---: | --- |
| 1000 | Tight prompt, large schema. Cuts total input by ~36% at 92% full table recall on BIRD. |
| 2000 | Default. 97.4% full-recall at 17% token reduction on BIRD. |
| 4000 | Relaxed prompt. 97.4% full-recall at 7.7% reduction; useful when schemas are large and the model needs room. |

The sweet spot on the BIRD mini-dev suite is 2000 tokens. That is the default.

### Switching selectors

The default selector is `CoverageSelector`, the value-grounded submodular
algorithm described in [`../DESIGN.md`](../DESIGN.md). For benchmarking or
ablation, swap in `RelevanceGreedySelector`, the BM25 baseline:

```python
from sqltok import SchemaBudgetManager, RelevanceGreedySelector

mgr = SchemaBudgetManager(
    schema,
    selector=RelevanceGreedySelector(schema),
)
```

### Tuning FK expansion

`CoverageSelector` accepts `fk_min_links` to trade recall for tokens. The
default `fk_min_links=1` maximises recall. Set it to `2` to favour precision and
token savings:

```python
from sqltok import SchemaBudgetManager, CoverageSelector

mgr = SchemaBudgetManager(
    schema,
    selector=CoverageSelector(schema, fk_min_links=2),
)
```

At `fk_min_links=2` on BIRD mini-dev, full-recall drops to roughly 81-86% while
mean schema tokens fall to 553-819.

### Including sample rows

Each included table can carry one example row as a comment. This costs extra
tokens but often helps the model infer formats and value distributions. Set
`include_sample_rows=True` (the default) or `False` to disable.

If a table does not fit with its sample row, the row is dropped before the table
is dropped, so the schema is never empty.

### Building from an introspected schema

For full control, introspect the schema yourself, then pass it to the manager:

```python
from sqltok import SchemaBudgetManager
from sqltok.introspect import introspect_sqlite

schema = introspect_sqlite("db.sqlite", sample_rows=5)
mgr = SchemaBudgetManager(schema, encoding_name="cl100k_base")
ctx = mgr.build_context("revenue by region", token_budget=2000)
```

### Measuring tokens yourself

Use `count_tokens` to measure arbitrary strings with the same encoding the
manager uses:

```python
mgr = SchemaBudgetManager.from_sqlite("db.sqlite")
print(mgr.count_tokens(ctx.text))   # same as ctx.token_count
```

### Inspecting the baseline dump

The full schema dump is the benchmark baseline. Use `full_schema_text` to see it:

```python
baseline = mgr.full_schema_text(include_sample_rows=True)
print(f"Baseline tokens: {mgr.count_tokens(baseline)}")
```

## Troubleshooting

### "ModuleNotFoundError: No module named 'tiktoken'"

Install the core dependency: `pip install tiktoken`. If you are in a virtual
environment, make sure it is activated.

### "ModuleNotFoundError: No module named 'bm25s'"

`bm25s` is a core dependency. Reinstall: `pip install sqltok`.

### Token budget too tight

If `ctx.token_count` is much smaller than `token_budget`, the schema may be
small. SQLTok guarantees the context fits within the budget, but it does not
waste budget padding. If you need a larger context, raise the budget.

### No tables selected

This happens when the question contains no grounded mentions and the schema is
too large to fit even the smallest table within the budget. Raise the budget or
use a selector that does not require grounding.

### "DDLParseError" when using from_ddl

The DDL parser uses `sqlglot`. Make sure your DDL is valid SQL. Common issues:
missing semicolons between statements, unsupported dialect-specific syntax, or
non-`CREATE TABLE` statements mixed in.

### Benchmark setup

To run the BIRD benchmark locally, see [`../benchmarks/README.md`](../benchmarks/README.md).
The smoke test needs no API key:

```bash
python benchmarks/make_sample_data.py
python benchmarks/run_bird.py --provider mock --data-dir benchmarks/sample_data --limit 5
```

For the full BIRD mini-dev run with a local model through Ollama:

```bash
bash benchmarks/download.sh
ollama pull qwen2.5-coder:7b
python benchmarks/run_bird.py --provider ollama --model qwen2.5-coder:7b \
    --questions benchmarks/data/minidev/MINIDEV/mini_dev_sqlite.json \
    --db-root  benchmarks/data/minidev/MINIDEV/dev_databases \
    --budgets 1000 2000 4000
```

Execution accuracy is scored with the official BIRD script; see
`benchmarks/third_party/bird_eval/README.md`. Paste the numbers into
[`../benchmarks/RESULTS.md`](../benchmarks/RESULTS.md).

## Real-world example: SQLite Northwind schema

The classic Northwind schema is a good hands-on example. Create the database,
then query it:

```python
import sqlite3
from sqltok import SchemaBudgetManager

# Create a minimal Northwind in memory.
conn = sqlite3.connect(":memory:")
conn.executescript("""
CREATE TABLE customers (
  customer_id INTEGER PRIMARY KEY,
  company_name TEXT NOT NULL,
  country TEXT
);
CREATE TABLE orders (
  order_id INTEGER PRIMARY KEY,
  customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
  order_date TEXT,
  freight REAL
);
CREATE TABLE order_details (
  order_id INTEGER NOT NULL REFERENCES orders(order_id),
  product_id INTEGER NOT NULL,
  unit_price REAL NOT NULL,
  quantity INTEGER NOT NULL,
  PRIMARY KEY (order_id, product_id)
);
CREATE TABLE products (
  product_id INTEGER PRIMARY KEY,
  product_name TEXT NOT NULL,
  category TEXT,
  unit_price REAL
);
INSERT INTO customers VALUES (1, 'Ernst Handel', 'Austria');
INSERT INTO customers VALUES (2, 'Suprêmes Délices', 'Belgium');
INSERT INTO customers VALUES (3, 'Hanari Carnes', 'Brazil');
INSERT INTO orders VALUES (1, 1, '2026-01-15', 32.38);
INSERT INTO orders VALUES (2, 2, '2026-01-16', 11.61);
INSERT INTO order_details VALUES (1, 1, 14.0, 12);
INSERT INTO order_details VALUES (1, 2, 9.8, 10);
INSERT INTO products VALUES (1, 'Chai', 'Beverages', 18.0);
INSERT INTO products VALUES (2, 'Chang', 'Beverages', 19.0);
""")
conn.close()

mgr = SchemaBudgetManager.from_sqlite(":memory:")
# The manager has already loaded the schema above; rebuild from the file.
# In practice you would pass the file path:
# mgr = SchemaBudgetManager.from_sqlite("northwind.sqlite")

# Alternatively, from the DDL directly:
ddl = """
CREATE TABLE customers (
  customer_id INTEGER PRIMARY KEY,
  company_name TEXT NOT NULL,
  country TEXT
);
CREATE TABLE orders (
  order_id INTEGER PRIMARY KEY,
  customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
  order_date TEXT,
  freight REAL
);
CREATE TABLE order_details (
  order_id INTEGER NOT NULL REFERENCES orders(order_id),
  product_id INTEGER NOT NULL,
  unit_price REAL NOT NULL,
  quantity INTEGER NOT NULL,
  PRIMARY KEY (order_id, product_id)
);
CREATE TABLE products (
  product_id INTEGER PRIMARY KEY,
  product_name TEXT NOT NULL,
  category TEXT,
  unit_price REAL
);
"""
mgr = SchemaBudgetManager.from_ddl(ddl)

ctx = mgr.build_context(
    question="total freight for orders by customers in Austria",
    token_budget=2000,
    include_sample_rows=True,
)

print("Selected tables:", ctx.tables)
print("Token count:", ctx.token_count)
print("Coverage:", f"{ctx.covered_weight:.0%}")
print()
print(ctx.text)
```

Expected output (selected tables may vary slightly depending on mention
grounding, but `customers` and `orders` will be selected because "Austria"
grounds to `customers` and "freight" grounds to `orders`):

```
Selected tables: ['customers', 'orders']
Token count: 200   # measured, well within budget
Coverage: 100%

CREATE TABLE customers (
  customer_id INTEGER PRIMARY KEY,
  company_name TEXT NOT NULL,
  country TEXT
);
-- example row: customer_id=1, company_name=Ernst Handel, country=Austria

CREATE TABLE orders (
  order_id INTEGER PRIMARY KEY,
  customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
  order_date TEXT,
  freight REAL
);
-- example row: order_id=1, customer_id=1, order_date=2026-01-15, freight=32.38
```

## Performance expectations

On BIRD mini-dev (500 questions, 11 SQLite databases), measured with
`tiktoken` (`cl100k_base`):

| Budget | Full-recall | Total input reduction |
| ---: | ---: | ---: |
| 1000 | 91.8% | 36.3% |
| 2000 | 97.4% | 17.2% |
| 4000 | 97.4% | 7.7% |

These numbers are deterministic and require no model. Execution accuracy needs a
real LLM; see [`../benchmarks/RESULTS.md`](../benchmarks/RESULTS.md) for
instructions.

## Next steps

- Read the [design rationale](../DESIGN.md) to understand the algorithm and its
  guarantees.
- Browse the [API reference](../API.md) for every public class and method.
- Run the [benchmark harness](../benchmarks/README.md) on your own schemas.
- Explore the [visual guide](../blog/visual-guide-to-sqltok.md) for an
  illustrated walkthrough of the pipeline.
