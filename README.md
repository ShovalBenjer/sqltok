<div align="center">

<img src="assets/logo.png" alt="SQLTok — Text-to-SQL token optimization and schema budget manager for LLM agents" width="320" />

# SQLTok — Schema Token Budget Manager for Text-to-SQL

**Cut LLM prompt costs in Text-to-SQL / NL2SQL by sending only the schema that matters — within a hard token budget, with guaranteed-joinable tables.**

[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/ShovalBenjer/sqltok/actions/workflows/ci.yml/badge.svg)](https://github.com/ShovalBenjer/sqltok/actions/workflows/ci.yml)
[![Linting: Ruff](https://img.shields.io/badge/linting-ruff-261230.svg)](https://github.com/astral-sh/ruff)
[![Typed: mypy](https://img.shields.io/badge/typed-mypy-2a6db2.svg)](https://mypy-lang.org/)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](#-contributing)

*Keywords: Text-to-SQL · NL2SQL · LLM token optimization · prompt compression · schema linking · schema retrieval · BIRD benchmark · tiktoken · submodular optimization · MinHash LSH · RAG for databases*

</div>

---

## 📌 What is SQLTok?

When an LLM writes SQL from natural language, it needs to see the database schema. Dumping the **entire** schema into every prompt is the dominant, hidden cost of production Text-to-SQL: a 3,000-table warehouse routinely produces **50,000+ token prompts**, which are expensive, slow, and *less accurate* (the model drowns in irrelevant tables).

**SQLTok is a drop-in Python library that selects only the relevant tables/columns for a given question, within a configurable token budget**, and emits a compact `CREATE TABLE`-style schema string for your prompt. Token counts are **measured with `tiktoken`** (never estimated), and the selected tables are guaranteed to be **join-connected via foreign keys** so the model can actually write the joins.

```python
from sqltok import SchemaBudgetManager

mgr = SchemaBudgetManager.from_sqlite("northwind.sqlite")
ctx = mgr.build_context("total order amount for customers in France", token_budget=2000)

print(ctx.text)          # compact CREATE TABLE schema, ≤ 2000 tokens
print(ctx.tables)        # ['customers', 'orders']
print(ctx.token_count)   # 101  (measured, guaranteed ≤ budget)
```

> **v0.1 scope:** the Schema Token Budget Manager + a BIRD benchmark harness — shipped small and correct. The semantic cache, intent canonicalizer, and framework integrations are on the [roadmap](#-roadmap), not in this release.

---

## ✨ Why SQLTok (and why not just BM25?)

Most "schema retrieval" is top-_k_ keyword matching. That breaks in three ways SQLTok fixes:

| Problem with naive retrieval | SQLTok's answer |
| --- | --- |
| **Mentions hide in cell values.** "France" is a *value* in `customers.country`, never a column name — BM25 over names misses it. | **Native value grounding** via MinHash + LSH over sampled cell values. |
| **Top-_k_ ignores the budget and redundancy.** It can blow the token ceiling or pick 3 tables covering the same thing. | **Submodular coverage** under a hard token budget (diminishing returns ⇒ no redundancy; `(1−1/e)` guarantee). |
| **Retrieved tables may not be joinable.** Two relevant tables with no FK path ⇒ the LLM hallucinates joins. | **Foreign-key Steiner connectivity** adds the minimal bridge tables. |

BM25 isn't gone — it ships as the honest **baseline** (`RelevanceGreedySelector`) so every benchmark gain is attributable. The **default** selector is the value-grounded submodular algorithm below. Everything is **native Python + NumPy, deterministic, offline** (no heavy deps, no network in the core).

---

## 🚀 Features

- 🎯 **Hard token budget** — output is re-measured with `tiktoken`; it *cannot* exceed your ceiling.
- 🔎 **Value-aware schema linking** — grounds question mentions to table/column names **and cell values** (MinHash + banded LSH).
- 🧮 **Submodular selection** — maximizes mention coverage per token (CELF lazy greedy + knapsack correction).
- 🔗 **Joinable by construction** — foreign-key Steiner bridges guarantee a connected sub-schema.
- 🧩 **Pluggable strategies** — `SchemaSelector` Protocol; swap in BM25, or future rerank / agentic selectors.
- 📏 **Real tokenization** — `cl100k_base` by default, configurable.
- 🧪 **Proven** — 44 deterministic tests, `ruff` + `mypy` clean, CI on 3.11/3.12. No API keys needed for tests.
- 📊 **BIRD benchmark harness** — baseline vs SQLTok arms, resumable response caching, **official** BIRD execution-accuracy scoring.

---

## 📦 Install

```bash
pip install sqltok
```

Core dependencies are light and offline: `tiktoken`, `bm25s`, `sqlglot`, `numpy`.
Optional extras: `sqltok[embeddings]` · `sqltok[benchmark]` (Anthropic/OpenAI) · `sqltok[dev]`.

---

## ⚡ Quickstart

```python
from sqltok import SchemaBudgetManager

# Build from a live SQLite DB (introspects tables, FKs, and samples cell values)…
mgr = SchemaBudgetManager.from_sqlite("path/to/db.sqlite")
# …or from raw DDL:  SchemaBudgetManager.from_ddl(create_table_sql)

ctx = mgr.build_context(
    question="What was the total order amount for customers in France?",
    token_budget=2000,          # hard ceiling on schema-context tokens
    include_sample_rows=True,   # one example row per included table
)

prompt = f"""Database schema:
{ctx.text}

Question: What was the total order amount for customers in France?
SQLite query:"""

print(ctx.tables)         # ['customers', 'orders']
print(ctx.token_count)    # measured with tiktoken; guaranteed ≤ token_budget
print(ctx.bridge_tables)  # FK bridges added to keep the selection joinable
print(ctx.covered_weight) # fraction of grounded question "mentions" covered
```

Use the BM25 baseline selector explicitly:

```python
from sqltok import SchemaBudgetManager, RelevanceGreedySelector
from sqltok.introspect import introspect_sqlite

schema = introspect_sqlite("db.sqlite")
mgr = SchemaBudgetManager(schema, selector=RelevanceGreedySelector(schema))
```

---

## 🧠 How it works — every algorithm, step by step

SQLTok turns *(schema, question, budget)* into a budgeted, joinable schema string in four stages:

```
            ┌──────────────┐   ┌───────────────┐   ┌──────────────────┐   ┌────────────────┐
 question → │ 1. Grounding │ → │ 2. Coverage   │ → │ 3. FK-Steiner    │ → │ SchemaContext  │
  schema  → │  (what hits  │   │  (submodular  │   │  connectivity    │   │ text + tables  │
  budget  → │   what)      │   │   budgeting)  │   │  (joinable)      │   │ + token_count  │
            └──────────────┘   └───────────────┘   └──────────────────┘   └────────────────┘
```

### Stage 1 — Value grounding: *which words touch which tables*

**Goal:** a matrix `cover[table, mention] ∈ [0,1]` + a weight per mention.

1. **Mention extraction** (`grounding/text.py`). Pull candidate phrases from the question: 1–3 word n-grams plus quoted literals, trimming stopwords from the edges.
   `"total revenue by region"` → `total revenue`, `revenue`, `region`.

2. **Character shingling.** Each string becomes a set of 3-character substrings:
   `"France"` → `{fra, ran, anc, nce}`. Character (not word) shingles give **fuzzy** matching robust to plurals, casing, and typos (`widgets` ≈ `widget`).

3. **MinHash** (`grounding/minhash.py`). Each shingle set is reduced to a length-64 signature. The defining property:
   > **P(minhashᵢ(A) = minhashᵢ(B)) = |A∩B| / |A∪B| = Jaccard(A, B).**

   So `mean(sig_A == sig_B)` is an **unbiased estimate of Jaccard similarity** — comparing two 64-int vectors instead of two raw sets. Fixed seeds ⇒ fully deterministic.

4. **Banded LSH** (`grounding/lsh.py`). We index every schema string — table names, column names, and **sampled cell values** — by its signature, split into 32 bands × 2 rows. Items that match a whole band land in the same bucket; a query only inspects colliding buckets. This is *candidate generation* in ~O(1) instead of scanning every value. Collision threshold ≈ `(1/bands)^(1/rows)` ≈ **0.18**, tuned for high recall. (This is the CHESS value-grounding idea, reimplemented natively.)

5. **Affinity + self-supervised IDF** (`grounding/affinity.py`). For each mention we take the best estimated-Jaccard match per table → `cover`. Then each mention is weighted by an **inverse document frequency learned from *this* schema**:
   > `weight(m) = log(1 + num_tables / df(m))`, where `df(m)` = how many tables the mention touches.

   A mention hitting *every* table (`id`, `name`) carries ~0 weight; one hitting a *single* table is highly discriminative. **No generic English corpus — the signal comes from your database.**

**Why it works:** the killer case is `"widgets"`, a *value* in `products.category` and nowhere in any column name. Name-based BM25 can't see it; the LSH-over-values path grounds it to `products` with high affinity.

### Stage 2 — Submodular budgeting: *pick the best tables per token*

**Objective** (`select/coverage.py`):
> **f(S) = Σₘ weight(m) · max₍T∈S₎ cover(m, T)**

This is **weighted maximum coverage**: each mention scores via the *best* table that covers it.

- **Why `max` (and why it's submodular).** If a mention is already covered, another table covering it adds **zero** marginal value → diminishing returns are built in, so **redundancy is handled for free** and `f` is monotone & submodular. For such functions the greedy maximizer has the classic **`(1 − 1/e) ≈ 63%`** approximation guarantee — not just a heuristic, a bound.

- **Knapsack via cost-benefit greedy.** Tables have different *token costs*. So at each step we pick the table maximizing **marginal-gain ÷ token-cost** (the AdaGReS token-budgeted, redundancy-aware rule), committing it only if the **re-measured** full context still fits the budget.

- **CELF lazy evaluation.** Because marginal gains only *decrease* as we add tables (submodularity), we keep a priority queue and recompute a candidate's gain only when it bubbles to the top. If its timestamp is current, it's provably the best next pick. This turns hundreds of re-evaluations into a handful — the part that scales to wide schemas.

- **KMS correction.** Ratio-greedy can be fooled by one huge high-value table, so we also compare against the *single best table that fits* (Khuller–Moss–Sviridenko) and keep whichever covers more — restoring the constant-factor knapsack guarantee.

- **Fallback.** If nothing grounds (a totally out-of-vocabulary question), we pack smallest-tables-first so the output is never empty — and always under budget.

### Stage 3 — Foreign-key Steiner connectivity: *make it joinable*

A relevance-only set can contain `products` and `orders` with **no direct join** — the LLM then invents a wrong `JOIN`. SQLTok (`select/connect.py`):

1. Builds the undirected foreign-key graph.
2. Checks if the selected tables form one connected component.
3. If not, finds the **shortest FK path** (BFS) between components and adds the minimal **bridge tables** (e.g. `line_items` connecting `products`↔`orders`) — budget permitting.

This is a heuristic **Steiner-tree** over the FK graph, grounded in AutoLink's insight that foreign keys are the *natural bridges* between relevant tables. Result: a sub-schema that is not just relevant but **executably joinable**.

### Stage 4 — The hard budget guarantee

Every tentative add (`select/base.py::BudgetPacker.try_add`) **renders the full context and counts it with `tiktoken`**; a table is committed only if the total stays ≤ budget (falling back to "no sample row" before dropping the table). Because the *actual string* is measured at every step, `token_count ≤ token_budget` is an invariant that no selection logic can violate.

---

## 🏗️ Architecture

```
sqltok/
├── models.py          # Schema / Table / Column / ForeignKey + compact DDL rendering
├── tokenizer.py       # tiktoken wrapper (real token counts)
├── ddl.py             # sqlglot CREATE TABLE parser
├── introspect.py      # SQLite introspection + cell-value sampling
├── grounding/         # ── Stage 1: native value grounding ──
│   ├── text.py        #   mention extraction + char shingles
│   ├── minhash.py     #   MinHash (Jaccard estimation)
│   ├── lsh.py         #   banded LSH (candidate generation)
│   └── affinity.py    #   cover matrix + self-supervised IDF
├── select/            # ── Stages 2–4: selection strategies ──
│   ├── base.py        #   SchemaSelector Protocol + BudgetPacker (hard ceiling)
│   ├── coverage.py    #   CoverageSelector (default): submodular CELF greedy
│   ├── connect.py     #   FK-Steiner connectivity
│   ├── greedy.py      #   RelevanceGreedySelector (BM25 baseline)
│   └── stubs.py       #   Rerank / Agentic selectors (v0.2)
├── manager.py         # SchemaBudgetManager (public API)
└── context.py         # SchemaContext (result)
```

---

## 📊 Benchmark (BIRD mini-dev)

Two arms, **same model and same prompt template**, differing only in schema context: `baseline` (full schema dump) vs `sqltok @ {1000, 2000, 4000}` token budgets. Execution accuracy is scored with **BIRD's official** script (no homemade SQL checker). See [`benchmarks/`](benchmarks/).

| arm | schema tok (mean) | schema tok (p95) | total input tok | exec acc | est. cost |
|-----|------:|------:|------:|------:|------:|
| baseline (full dump) | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ |
| sqltok @ 1000 | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ |
| sqltok @ 2000 | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ |
| sqltok @ 4000 | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ |

> Numbers are filled in from a full run. The underlying technique — budget-aware schema reduction — has shown **up to ~87% schema-token reduction at competitive accuracy** in the literature it builds on ([Datalake Agent](https://arxiv.org/abs/2510.14808)).

**Reproduce for free (no API keys, mock LLM):**

```bash
python benchmarks/make_sample_data.py
python benchmarks/run_bird.py --provider mock --data-dir benchmarks/sample_data --limit 5
```

**Real run (BIRD mini-dev):**

```bash
bash benchmarks/download.sh                      # fetch the dataset (not committed)
export ANTHROPIC_API_KEY=...                      # or OPENAI_API_KEY
python benchmarks/run_bird.py --provider anthropic --model claude-3-5-sonnet \
    --data-dir benchmarks/data --budgets 1000 2000 4000 --in-price 3 --out-price 15
```

Responses are cached on disk (keyed by hash of prompt+model), so reruns are free and the run is resumable.

---

## 🔌 API at a glance

| Symbol | Purpose |
| --- | --- |
| `SchemaBudgetManager.from_sqlite(path)` / `.from_ddl(sql)` | Build a manager from a DB or DDL. |
| `mgr.build_context(question, token_budget=…, include_sample_rows=…, fk_expand=…)` | Return a `SchemaContext`. |
| `SchemaContext.text / .tables / .token_count / .bridge_tables / .covered_weight` | The result fields. |
| `CoverageSelector` *(default)* | Value-grounded submodular selector. |
| `RelevanceGreedySelector` | BM25 baseline / ablation. |
| `SchemaGrounding` | Standalone grounding (cover matrix + weights). |
| `SchemaSelector` | Protocol to implement your own strategy. |

---

## 🗺️ Roadmap

Drawn from the research these ideas build on:

- **SID semantic cache** — canonicalize NL/SQL into a hashable *SQL Intent Descriptor*; exact + derivation (roll-up / filter-down) cache hits.
- **Intent canonicalizer** — `sqlglot` AST → SID for SQL; confidence-gated NL → SID.
- **Invalidation tag registry** — RTK-Query-style `providesTags` / `invalidatesTags` tied to table lineage.
- **Cache backends** — Redis / DuckDB; KV-prefix alignment for provider prompt caches.
- **Selectors** — cross-encoder `RerankSelector`; LLM-agentic `AgenticSelector` (Datalake Agent / AutoLink style); embedding-hybrid retrieval.
- **Integrations** — LangChain · LlamaIndex · Vanna shims.

---

## 📚 Research & references

SQLTok packages and combines techniques from recent, verified work. If you build on it, please credit them too.

**Foundations of the library (cite these):**

1. **Datalake Agent** — *Agentic NL2SQL to Reduce Computational Costs* — arXiv:[2510.14808](https://arxiv.org/abs/2510.14808). Budget-aware lazy schema discovery (up to 87% token reduction).
2. **OLAP Intent Signature / LLMSigCache** — *Semantic Caching for OLAP via LLM-Based Query Canonicalization* (DOLAP 2026) — arXiv:[2602.19811](https://arxiv.org/abs/2602.19811). The intent-signature cache the v0.2 SID layer generalizes.
3. **AgentSM** — *Semantic Memory for Agentic Text-to-SQL* — arXiv:[2601.15709](https://arxiv.org/abs/2601.15709). Reasoning-path reuse for the v0.2 memory/derivations roadmap.

**Directly informing the default selector:**

4. **Bidirectional Schema Linking** — Findings of EACL 2026 — arXiv:[2510.14296](https://arxiv.org/abs/2510.14296). Schema linking as a first-class retrieval problem.
5. **AutoLink** — *Autonomous Schema Exploration and Expansion at Scale* — arXiv:[2511.17190](https://arxiv.org/abs/2511.17190). Foreign keys as natural bridges (Steiner connectivity).
6. **AdaGReS** — *Adaptive Greedy Context Selection via Redundancy-Aware Scoring for Token-Budgeted RAG* — arXiv:[2512.25052](https://arxiv.org/abs/2512.25052). Token-budgeted greedy.
7. **Sub-SA** — *Submodular Selective Annotation* — arXiv:[2407.05693](https://arxiv.org/abs/2407.05693). Submodular reward − diversity selection.
8. **CHESS** — *Contextual Harnessing for Efficient SQL Synthesis* — arXiv:[2405.16755](https://arxiv.org/abs/2405.16755). LSH value grounding.

**Classical results underpinning the math:** Broder, *On the resemblance and containment of documents* (MinHash, 1997); Indyk & Motwani (LSH, 1998); Nemhauser, Wolsey & Fisher, *An analysis of approximations for maximizing submodular set functions* (the `(1−1/e)` bound, 1978); Khuller, Moss & Naor (budgeted maximum coverage, 1999); Leskovec et al., *Cost-effective Outbreak Detection* (CELF, 2007).

### Cite SQLTok

```bibtex
@software{sqltok2026,
  title   = {SQLTok: A Schema Token Budget Manager for Text-to-SQL},
  author  = {Benjer, Shoval and contributors},
  year    = {2026},
  url     = {https://github.com/ShovalBenjer/sqltok},
  note    = {Value-grounded submodular schema selection under a token budget}
}
```

---

## 🤝 Contributing

Issues and PRs are welcome.

```bash
git clone https://github.com/ShovalBenjer/sqltok && cd sqltok
pip install -e ".[dev]"
python -m pytest          # tests require no API keys
ruff check . && mypy sqltok/
```

If SQLTok saves you tokens, a ⭐ helps others find it.

---

## 📖 Glossary

| Term | Meaning |
| --- | --- |
| **Text-to-SQL / NL2SQL** | Translating a natural-language question into an executable SQL query. |
| **Schema linking** | Mapping words in a question to the relevant tables/columns of a database. |
| **Schema context** | The slice of schema (DDL) placed in the LLM prompt. SQLTok minimizes this. |
| **Token budget** | A hard upper bound on how many tokens the schema context may use. |
| **`tiktoken`** | OpenAI's BPE tokenizer; used here to count tokens exactly (`cl100k_base` default). |
| **Mention** | A candidate phrase extracted from the question (n-gram or quoted literal). |
| **Grounding** | Linking a mention to schema elements — including **cell values**, not just names. |
| **Shingle** | A fixed-length substring (here 3 chars) used to compare strings fuzzily. |
| **Jaccard similarity** | `|A∩B| / |A∪B|` — overlap between two sets, in `[0,1]`. |
| **MinHash** | A sketch that estimates Jaccard by comparing fixed-length signatures. |
| **LSH (Locality-Sensitive Hashing)** | Hashing that puts similar items in the same bucket for fast candidate lookup. |
| **Band / row (LSH)** | The signature is split into bands of rows; a full-band match = a candidate. |
| **IDF (self-supervised)** | Down-weights mentions that match many tables; computed from *your* schema. |
| **Coverage function** | `f(S)=Σ weight·max cover` — how much question "weight" a table set explains. |
| **Submodular** | Diminishing returns: adding an element helps less as the set grows. |
| **Monotone** | Adding elements never decreases the objective. |
| **`(1−1/e)` guarantee** | Greedy gets ≥ 63% of the optimum for monotone submodular maximization. |
| **Knapsack constraint** | Selection under a budget where items have unequal costs (tokens). |
| **Cost-benefit greedy** | Pick by marginal-gain ÷ cost — the budgeted greedy rule. |
| **CELF** | Lazy greedy using a priority queue; exploits submodularity to skip recomputation. |
| **KMS correction** | Compare greedy vs the best single feasible item to keep the knapsack bound. |
| **Foreign-key (FK) graph** | Tables as nodes, foreign keys as edges. |
| **Steiner tree** | A minimal connected subgraph spanning a target set, possibly via extra nodes. |
| **Bridge table** | An intermediate table added so selected tables become join-connected. |
| **Selector** | A pluggable strategy (`SchemaSelector`) that turns a question into a context. |
| **Sample row** | One example data row per table, added to the prompt when budget allows. |
| **BIRD** | A large, realistic Text-to-SQL benchmark; `mini-dev` is its 500-question subset. |
| **Execution accuracy** | Correctness measured by comparing executed result sets, not SQL strings. |

---

<div align="center">

**SQLTok** — send less schema, write better SQL, pay fewer tokens.

MIT licensed · Built on recent 2024–2026 Text-to-SQL research · [Report an issue](https://github.com/ShovalBenjer/sqltok/issues)

</div>
