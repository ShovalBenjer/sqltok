# SQLTok API Reference

## Overview

SQLTok exposes a small, stable public surface. The typical entry point is
`SchemaBudgetManager`, which turns a database (or DDL) and a question into a
budgeted schema context. Below every public symbol is documented with its
signature, arguments, return type, and an example.

All examples assume `import sqltok` or the specific imports shown.

## Package-level exports

```python
from sqltok import (
    SchemaBudgetManager,
    SchemaContext,
    Schema,
    Table,
    Column,
    ForeignKey,
    SchemaSelector,
    CoverageSelector,
    RelevanceGreedySelector,
    RerankSelector,
    AgenticSelector,
    SchemaGrounding,
    TableRetriever,
    RankedTable,
    TokenCounter,
    parse_ddl,
    DDLParseError,
    introspect_sqlite,
    __version__,
)
```

`__version__` is the current package version string (e.g. `"0.1.0"`).

---

## SchemaBudgetManager

The main entry point. Wraps a parsed schema and a selector strategy, and turns
a natural-language question plus a token budget into a compact, prompt-ready
schema context.

```python
from sqltok import SchemaBudgetManager
```

### Constructor

```python
SchemaBudgetManager(schema, *, encoding_name="cl100k_base", selector=None)
```

| Parameter | Type | Default | Purpose |
| --- | --- | --- | --- | --- |
| `schema` | `Schema` | required | The schema to serve contexts from. Build one with `introspect_sqlite`, `parse_ddl`, or construct `Schema` directly. |
| `encoding_name` | `str` | `"cl100k_base"` | `tiktoken` encoding used for all token counting. |
| `selector` | `SchemaSelector` or `None` | `None` | Selection strategy. Defaults to `CoverageSelector(schema)`. |

### Class methods

#### `SchemaBudgetManager.from_sqlite(db_path, *, sample_rows=3, encoding_name="cl100k_base", selector=None)`

Build a manager by introspecting a SQLite database file.

```python
mgr = SchemaBudgetManager.from_sqlite("northwind.sqlite")
```

| Parameter | Type | Default | Purpose |
| --- | --- | --- | --- |
| `db_path` | `str` or `Path` | required | Path to the SQLite database. |
| `sample_rows` | `int` | `3` | Rows to sample per table for values and example rows. |
| `encoding_name` | `str` | `"cl100k_base"` | `tiktoken` encoding name. |
| `selector` | `SchemaSelector` or `None` | `None` | Optional selection strategy override. |

#### `SchemaBudgetManager.from_ddl(ddl, *, dialect=None, encoding_name="cl100k_base", selector=None)`

Build a manager from raw `CREATE TABLE` DDL.

```python
ddl = """
CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE posts (id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), body TEXT);
"""
mgr = SchemaBudgetManager.from_ddl(ddl)
```

| Parameter | Type | Default | Purpose |
| --- | --- | --- | --- |
| `ddl` | `str` | required | One or more `CREATE TABLE` statements. |
| `dialect` | `str` or `None` | `None` | Optional `sqlglot` dialect name (`"sqlite"`, `"postgres"`, `"mysql"`, etc.). |
| `encoding_name` | `str` | `"cl100k_base"` | `tiktoken` encoding name. |
| `selector` | `SchemaSelector` or `None` | `None` | Optional selection strategy override. |

### Core methods

#### `build_context(question, *, token_budget=2000, include_sample_rows=True, fk_expand=True) -> SchemaContext`

Build a token-budgeted schema context for `question`. This is the method you
call per query.

```python
ctx = mgr.build_context(
    question="total orders for customers in France",
    token_budget=2000,
    include_sample_rows=True,
)
print(ctx.text)  # compact schema string
print(ctx.tables)  # selected table names
print(ctx.token_count)  # measured, <= budget
```

| Parameter | Type | Default | Purpose |
| --- | --- | --- | --- |
| `question` | `str` | required | The natural-language question to retrieve schema for. |
| `token_budget` | `int` | `2000` | Hard ceiling on schema-context tokens. `ctx.token_count` is guaranteed not to exceed this. |
| `include_sample_rows` | `bool` | `True` | Attach one example row per included table when it fits within budget. |
| `fk_expand` | `bool` | `True` | Add foreign-key bridge/neighbour tables so the selection is join-connected, budget permitting. |

**Raises:** `ValueError` if `token_budget <= 0`.

**Returns:** `SchemaContext` with the rendered text, selected tables, measured
token count, and metadata.

**Performance:** Selection is deterministic and sublinear in the number of
tables thanks to CELF lazy evaluation. The dominant cost is grounding
(`SchemaGrounding.ground`), which is near-constant time per question after the
initial LSH index is built.

#### `full_schema_text(*, include_sample_rows=True) -> str`

Return the entire schema as DDL. This is the benchmark *baseline* dump.

```python
baseline = mgr.full_schema_text()
print(f"Baseline tokens: {mgr.count_tokens(baseline)}")
```

#### `count_tokens(text) -> int`

Count tokens in `text` with this manager's encoding.

```python
n = mgr.count_tokens("SELECT * FROM users WHERE id = 1")
```

### Attributes

| Attribute | Type | Purpose |
| --- | --- | --- | --- |
| `schema` | `Schema` | The schema this manager serves. |
| `counter` | `TokenCounter` | The token counter instance. |
| `selector` | `SchemaSelector` | The active selection strategy. |

---

## SchemaContext

The result object returned by `SchemaBudgetManager.build_context`.

```python
from sqltok import SchemaContext
```

### Fields

| Field | Type | Purpose |
| --- | --- | --- |
| `text` | `str` | Compact `CREATE TABLE`-style schema string, ready to paste into a prompt. |
| `tables` | `list[str]` | Selected table names, in rendered order. |
| `token_count` | `int` | Real token count of `text`, measured with `tiktoken`. |
| `budget` | `int` | The token budget the context was built against. |
| `encoding_name` | `str` | The `tiktoken` encoding used to measure tokens. |
| `selector` | `str` | Name of the selection strategy that produced this context (e.g. `"coverage"`, `"relevance_greedy"`). |
| `bridge_tables` | `list[str]` | Tables added purely to make the selection join-connected (foreign-key Steiner bridges). |
| `fk_expanded` | `list[str]` | Tables added by plain foreign-key expansion (baseline selector); kept for backwards compatibility. |
| `covered_weight` | `float` | Fraction of total grounded mention weight covered by the selection (`0.0` for selectors that do not compute coverage). |

`SchemaContext` is a `@dataclass(slots=True)`. It also implements `__str__` to
return `text`, so `print(ctx)` prints the schema string.

---

## Schema

A collection of tables keyed by name (insertion-ordered).

```python
from sqltok import Schema
```

### Fields

| Field | Type | Purpose |
| --- | --- | --- |
| `tables` | `dict[str, Table]` | Map of table name to `Table`. Insertion-ordered (Python 3.7+). |

### Methods

#### `table_names() -> list[str]`

Return table names in insertion order.

#### `get(name) -> Table or None`

Return a table by name, or `None` if absent.

#### `fk_neighbors(name) -> list[str]`

Return tables directly connected to `name` by a foreign key. Includes both
outgoing edges (`name` references another table) and incoming edges (another
table references `name`). Sorted for deterministic ordering.

```python
schema = introspect_sqlite("db.sqlite")
neighbors = schema.fk_neighbors("orders")
# ['customers', 'order_details']
```

#### `render_full_ddl(*, include_sample_rows=False) -> str`

Render every table's DDL, joined by blank lines. This is the baseline dump used
in benchmarks.

```python
full = schema.render_full_ddl(include_sample_rows=True)
```

---

## Table

A table: its columns, foreign keys, and an optional example row.

```python
from sqltok import Table
```

### Fields

| Field | Type | Purpose |
| --- | --- | --- |
| `name` | `str` | Table name. |
| `columns` | `list[Column]` | Ordered list of columns. |
| `foreign_keys` | `list[ForeignKey]` | Outgoing foreign-key edges. |
| `sample_row` | `dict[str, object] or None` | One example row as a `{column: value}` mapping. |
| `description` | `str or None` | Optional human-authored table description. |

### Methods

#### `column_names() -> list[str]`

Return the ordered list of column names.

```python
t = schema.get("orders")
print(t.column_names())  # ['order_id', 'customer_id', 'order_date', 'freight']
```

#### `render_ddl(*, include_sample_row=False) -> str`

Render this table as a compact `CREATE TABLE` string.

```python
print(t.render_ddl(include_sample_row=True))
# CREATE TABLE orders (
#   order_id INTEGER PRIMARY KEY,
#   customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
#   order_date TEXT,
#   freight REAL
# );
# -- example row: order_id=1, customer_id=1, order_date=2026-01-15, freight=32.38
```

---

## Column

A single column in a table.

```python
from sqltok import Column
```

### Fields

| Field | Type | Purpose |
| --- | --- | --- |
| `name` | `str` | Column name. |
| `type` | `str` | SQL type as written in the source DDL (e.g. `"INTEGER"`). |
| `nullable` | `bool` | Whether the column accepts `NULL`. |
| `primary_key` | `bool` | Whether the column participates in the primary key. |
| `description` | `str or None` | Optional human-authored description (from a data dictionary). |
| `sample_values` | `list[str]` | Example values sampled from the database, used to enrich retrieval. Not rendered into the DDL. |

---

## ForeignKey

A foreign-key edge from `column` to `ref_table.ref_column`.

```python
from sqltok import ForeignKey
```

### Fields

| Field | Type | Purpose |
| --- | --- | --- |
| `column` | `str` | Local column name. |
| `ref_table` | `str` | Referenced table name. |
| `ref_column` | `str` | Referenced column name. |

---

## SchemaSelector (Protocol)

The pluggable selection strategy interface. Any object with a `name` attribute
and a `select` method matching this signature satisfies the protocol.

```python
from sqltok import SchemaSelector
```

### Methods

#### `select(question, *, token_budget, counter, include_sample_rows=True, fk_expand=True) -> SchemaContext`

Turn a question and a token budget into a `SchemaContext`.

| Parameter | Type | Purpose |
| --- | --- | --- |
| `question` | `str` | Natural-language question. |
| `token_budget` | `int` | Hard token ceiling. |
| `counter` | `TokenCounter` | Token counter for measuring output. |
| `include_sample_rows` | `bool` | Whether to attach example rows. |
| `fk_expand` | `bool` | Whether to add FK bridge tables. |

### Built-in implementations

- `CoverageSelector` (default)
- `RelevanceGreedySelector`
- `RerankSelector` (v0.2 stub, raises `NotImplementedError`)
- `AgenticSelector` (v0.2 stub, raises `NotImplementedError`)

To implement a custom selector, satisfy this protocol:

```python
class MySelector:
    name = "my_selector"

    def select(
        self, question, *, token_budget, counter, include_sample_rows=True, fk_expand=True
    ): ...
```

---

## CoverageSelector

The default selector. Value-grounded submodular mention coverage with CELF lazy
evaluation and foreign-key Steiner connectivity.

```python
from sqltok import CoverageSelector
```

### Constructor

```python
CoverageSelector(schema, *, grounding=None, fk_min_links=1)
```

| Parameter | Type | Default | Purpose |
| --- | --- | --- | --- |
| `schema` | `Schema` | required | The schema to select from. |
| `grounding` | `SchemaGrounding` or `None` | `None` | Prebuilt grounding. If `None`, one is constructed with default parameters. |
| `fk_min_links` | `int` | `1` | Minimum number of selected tables an FK neighbour must link to before it is pulled in. `1` maximises recall; `2` favours precision and token savings. |

### Methods

#### `select(question, *, token_budget, counter, include_sample_rows=True, fk_expand=True) -> SchemaContext`

Build a budgeted, join-connected schema context for `question`.

**Performance characteristics:**
- Grounding is near-constant after the initial LSH index build.
- CELF lazy evaluation reduces hundreds of candidate evaluations to a few heap
  operations.
- The `fk_min_links=2` setting trades roughly 10 percentage points of full-recall
  for 60-70% fewer mean schema tokens on BIRD mini-dev.

---

## RelevanceGreedySelector

BM25 baseline selector. Rank tables by keyword relevance, greedily pack them
under the budget, then pull in foreign-key neighbours.

```python
from sqltok import RelevanceGreedySelector
```

### Constructor

```python
RelevanceGreedySelector(schema, *, retriever=None, max_candidates=None)
```

| Parameter | Type | Default | Purpose |
| --- | --- | --- | --- |
| `schema` | `Schema` | required | The schema to select from. |
| `retriever` | `TableRetriever` or `None` | `None` | Prebuilt retriever. If `None`, one is created. |
| `max_candidates` | `int` or `None` | `None` | Cap on the number of top-ranked tables considered during the greedy fill. FK expansion can still reach beyond it. |

### Methods

#### `select(question, *, token_budget, counter, include_sample_rows=True, fk_expand=True) -> SchemaContext`

Build a budgeted schema context by greedy relevance packing.

**Performance:** Simpler than `CoverageSelector` but has no submodularity
guarantee. Used as the honest baseline in benchmarks.

---

## RerankSelector

v0.2 stub. Planned: rerank coverage candidates with a cross-encoder before
packing.

```python
from sqltok import RerankSelector
```

Calling `select` raises `NotImplementedError`.

---

## AgenticSelector

v0.2 stub. Planned: LLM-driven lazy schema discovery (Datalake Agent / AutoLink
style).

```python
from sqltok import AgenticSelector
```

Calling `select` raises `NotImplementedError`.

---

## SchemaGrounding

Build per-table coverage signals for questions over a fixed schema. This is the
stage that grounds mentions to tables via name matches and sampled cell values
(MinHash + LSH).

```python
from sqltok import SchemaGrounding
```

### Constructor

```python
SchemaGrounding(schema, *, max_values_per_column=20, shingle_size=3, num_perm=64, bands=32, rows=2, seed=1)
```

| Parameter | Type | Default | Purpose |
| --- | --- | --- | --- |
| `schema` | `Schema` | required | The schema to ground against. |
| `max_values_per_column` | `int` | `20` | Cap on distinct sampled values indexed per column. |
| `shingle_size` | `int` | `3` | Character n-gram size for fuzzy matching. |
| `num_perm` | `int` | `64` | Number of MinHash permutations (signature length). |
| `bands` | `int` | `32` | Number of LSH bands. |
| `rows` | `int` | `2` | Rows per band. |
| `seed` | `int` | `1` | Random seed for deterministic MinHash. |

**Performance:** The LSH index is built once in `__init__`. `ground(question)` is
near-constant time for typical schemas. The collision threshold is approximately
`(1 / bands) ** (1 / rows)` ~ 0.18, which favours recall.

### Methods

#### `ground(question) -> GroundedQuery`

Ground `question` and return its coverage matrix and weights.

```python
grounding = SchemaGrounding(schema)
gq = grounding.ground("total orders for customers in France")
print(gq.mentions)  # ['France', 'customers', 'orders', ...]
print(gq.cover.shape)  # (num_tables, num_mentions)
```

---

## GroundedQuery

The result of grounding one question against a schema.

```python
from sqltok import GroundedQuery
```

### Fields

| Field | Type | Purpose |
| --- | --- | --- |
| `table_order` | `list[str]` | Table names indexing the rows of `cover`. |
| `mentions` | `list[str]` | Grounded mention phrases (columns of `cover`). |
| `cover` | `np.ndarray` | `(num_tables, num_mentions)` affinity matrix in `[0, 1]`. |
| `weights` | `np.ndarray` | `(num_mentions,)` per-mention importance weights. |

---

## TableRetriever

Rank tables by relevance to a natural-language question using BM25, with an
optional dense-embedding signal.

```python
from sqltok import TableRetriever
```

### Constructor

```python
TableRetriever(schema, *, use_embeddings=False, embedding_fn=None, embedding_weight=0.5)
```

| Parameter | Type | Default | Purpose |
| --- | --- | --- | --- |
| `schema` | `Schema` | required | The schema whose tables are indexed. |
| `use_embeddings` | `bool` | `False` | If `True`, fuse a dense cosine-similarity score with BM25. Requires `embedding_fn`. |
| `embedding_fn` | `Callable[[Sequence[str]], np.ndarray]` or `None` | `None` | Callable mapping a sequence of strings to an `(n, d)` float array of embeddings. Only used when `use_embeddings` is `True`. |
| `embedding_weight` | `float` | `0.5` | Blend weight in `[0, 1]` for the embedding score when fusing with BM25. |

**Raises:** `ValueError` if `use_embeddings=True` and `embedding_fn` is `None`.

### Methods

#### `rank(question) -> list[RankedTable]`

Return all tables ranked by descending relevance to `question`. Ties are broken
by table name for deterministic ordering.

```python
retriever = TableRetriever(schema)
ranked = retriever.rank("total revenue by region")
for rt in ranked:
    print(rt.name, rt.score)
```

---

## RankedTable

A table name with its fused retrieval score.

```python
from sqltok import RankedTable
```

### Fields

| Field | Type | Purpose |
| --- | --- | --- |
| `name` | `str` | Table name. |
| `score` | `float` | Relevance score (higher is more relevant). |

---

## TokenCounter

Wraps a `tiktoken` encoding and counts tokens. Used internally by
`SchemaBudgetManager`; you can also use it directly.

```python
from sqltok import TokenCounter
```

### Constructor

```python
TokenCounter(encoding_name="cl100k_base")
```

| Parameter | Type | Default | Purpose |
| --- | --- | --- | --- |
| `encoding_name` | `str` | `"cl100k_base"` | Name of the `tiktoken` encoding to use. |

### Methods

#### `count(text) -> int`

Return the number of tokens in `text`.

```python
counter = TokenCounter()
n = counter.count("SELECT * FROM users WHERE id = 1")  # e.g. 10
```

#### `encoding_name` (attribute)

The name of the encoding in use (e.g. `"cl100k_base"`).

---

## parse_ddl

Parse `CREATE TABLE` DDL into a `Schema`.

```python
from sqltok import parse_ddl
```

```python
schema = parse_ddl(ddl, dialect=None)
```

| Parameter | Type | Default | Purpose |
| --- | --- | --- | --- |
| `ddl` | `str` | required | SQL text containing one or more `CREATE TABLE` statements. |
| `dialect` | `str` or `None` | `None` | Optional `sqlglot` dialect name. |

**Raises:** `DDLParseError` if the SQL cannot be parsed.

---

## DDLParseError

Raised when DDL cannot be parsed. Subclasses `ValueError`.

```python
from sqltok import DDLParseError
```

---

## introspect_sqlite

Build a `Schema` from a SQLite database file.

```python
from sqltok import introspect_sqlite
```

```python
schema = introspect_sqlite("db.sqlite", sample_rows=3, max_sample_values=5)
```

| Parameter | Type | Default | Purpose |
| --- | --- | --- | --- |
| `db_path` | `str` or `Path` | required | Path to a `.sqlite`/`.db` file. |
| `sample_rows` | `int` | `3` | Number of rows to sample per table for values and example rows. |
| `max_sample_values` | `int` | `5` | Max distinct sample values kept per column. |

**Raises:** `FileNotFoundError` if the database file does not exist.

---

## Performance summary

| Symbol | Complexity | Notes |
| --- | --- | --- |
| `SchemaBudgetManager.from_sqlite` | O(T * R) | T = tables, R = sampled rows. One-time cost. |
| `SchemaGrounding.__init__` | O(T * C * V) | Build LSH index. T = tables, C = columns, V = values per column. |
| `SchemaGrounding.ground` | O(1) average | Near-constant LSH lookup per question. |
| `CoverageSelector.select` | O(T log T) | CELF lazy evaluation dominates; T = candidate tables. |
| `RelevanceGreedySelector.select` | O(T log T) | BM25 ranking + greedy packing. |

Memory usage is dominated by the LSH signature matrix
(`num_perm * num_schema_strings` integers). For a 100-table schema with ~20
strings per table, this is roughly 64 * 2000 * 8 bytes ~ 1 MB.
