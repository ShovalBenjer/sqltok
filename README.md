# SQLTok

**SQLTok is a Schema Token Budget Manager for Text2SQL agents:** given a database
schema and a natural-language question, it selects only the most relevant
tables/columns within a hard token budget and emits a compact `CREATE TABLE`-style
schema context for your LLM prompt. Instead of top-k keyword retrieval, it frames
schema selection as **value-grounded submodular coverage over a foreign-key
Steiner graph**, so the returned schema is both budget-bounded and actually
join-connected.

> v0.1 ships exactly one thing, well: the schema budget manager + a BIRD
> benchmark harness. The semantic cache, intent canonicalizer, and framework
> integrations from the research are explicit roadmap items, not in this release.

## Why not just BM25?

BM25 is the *floor* SQLTok ships as a baseline — not the engine. The default
selector combines four ideas from accepted 2026 work into one native algorithm
(no heavy deps, no network, fully deterministic):

1. **Native value grounding** — a hand-rolled MinHash + banded LSH matches
   question mentions against sampled **cell values**, so `"France" → customers.country`
   even though "country" never appears in the question (the CHESS idea, our code).
2. **Submodular coverage** — maximise weighted coverage of grounded mentions,
   `f(S) = Σ_m w_m · max_{T∈S} cover(m,T)` (monotone submodular ⇒ `(1−1/e)`),
   with mention weights from a **self-supervised IDF learned from your DB**.
3. **Token-budgeted lazy greedy** — CELF cost-benefit greedy (marginal-gain /
   token-cost), re-measured with `tiktoken` so the budget is a hard ceiling.
4. **Foreign-key Steiner connectivity** — add the minimal bridge tables that make
   the selection joinable, the failure mode pure retrieval ignores.

## Install

```bash
pip install sqltok
```

Core has no heavy/network dependencies (`tiktoken`, `bm25s`, `sqlglot`, `numpy`).
Optional extras: `sqltok[embeddings]`, `sqltok[benchmark]`, `sqltok[dev]`.

## Quickstart

```python
from sqltok import SchemaBudgetManager

# From a SQLite file (introspects tables, FKs, and samples cell values)...
mgr = SchemaBudgetManager.from_sqlite("path/to/db.sqlite")
# ...or from raw DDL: SchemaBudgetManager.from_ddl(create_table_sql)

ctx = mgr.build_context(
    question="What was the total order amount for customers in France?",
    token_budget=2000,          # hard ceiling on schema-context tokens
    include_sample_rows=True,   # one example row per included table
)

print(ctx.text)            # compact CREATE TABLE-style schema for your prompt
print(ctx.tables)          # ['customers', 'orders']
print(ctx.token_count)     # measured with tiktoken; guaranteed <= token_budget
print(ctx.bridge_tables)   # FK Steiner bridges added for join-connectivity
```

Swap the strategy explicitly (the BM25 baseline, or a v0.2 stub):

```python
from sqltok import SchemaBudgetManager, RelevanceGreedySelector
from sqltok.introspect import introspect_sqlite

schema = introspect_sqlite("db.sqlite")
mgr = SchemaBudgetManager(schema, selector=RelevanceGreedySelector(schema))  # BM25 floor
```

## Benchmark results (BIRD mini-dev)

Two arms, same model + prompt, schema context only differs: **baseline** (full
dump) vs **sqltok** at 1000/2000/4000 token budgets. Execution accuracy is scored
with BIRD's **official** script. See [`benchmarks/`](benchmarks/).

| arm | schema tok (mean) | schema tok (p95) | total input tok | exec acc | est. cost |
|-----|------:|------:|------:|------:|------:|
| baseline (full dump) | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| sqltok @ 1000 | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| sqltok @ 2000 | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| sqltok @ 4000 | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |

_Placeholders until a full run is committed. Reproduce with a free, no-API smoke
run:_

```bash
python benchmarks/run_bird.py --provider mock --data-dir benchmarks/sample_data --limit 5
```

## Citations

SQLTok packages and combines techniques validated by recent research; if you use
it, please credit the underlying work:

- **Datalake Agent** — *Agentic NL2SQL to Reduce Computational Costs*,
  arXiv:[2510.14808](https://arxiv.org/abs/2510.14808). Budget-aware, lazy schema
  discovery (up to 87% token reduction) motivates the budget manager.
- **OLAP Intent Signature / LLMSigCache** — *Semantic Caching for OLAP via
  LLM-Based Query Canonicalization*, DOLAP 2026, arXiv:[2602.19811](https://arxiv.org/abs/2602.19811).
  The intent-signature cache SQLTok's v0.2 SID layer generalises.
- **AgentSM** — *Semantic Memory for Agentic Text-to-SQL*,
  arXiv:[2601.15709](https://arxiv.org/abs/2601.15709). Reasoning-path reuse for
  the v0.2 derivations/memory roadmap.

The default selector is additionally informed by: **Bidirectional Schema Linking**
(Findings of EACL 2026, arXiv:[2510.14296](https://arxiv.org/abs/2510.14296)),
**AutoLink** (arXiv:[2511.17190](https://arxiv.org/abs/2511.17190), FK paths as
bridges), **AdaGReS** (arXiv:[2512.25052](https://arxiv.org/abs/2512.25052),
token-budgeted redundancy-aware greedy), **Sub-SA**
(arXiv:[2407.05693](https://arxiv.org/abs/2407.05693), submodular reward−diversity),
and **CHESS** (LSH value grounding).

## Roadmap (v0.2+)

Future work, drawn from the research these ideas build on:

- **SID semantic cache** — canonicalize NL/SQL to a hashable SQL Intent
  Descriptor; exact + derivation (roll-up / filter-down) cache hits.
- **Intent canonicalizer** — `sqlglot` AST → SID for SQL; confidence-gated NL → SID.
- **Invalidation tag registry** — RTK-Query-style `providesTags`/`invalidatesTags`
  tied to table lineage.
- **Cache backends** — Redis / DuckDB; KV-prefix alignment for provider prompt caches.
- **Selectors** — cross-encoder `RerankSelector` and LLM-agentic `AgenticSelector`
  (Datalake Agent / AutoLink style); embedding-hybrid retrieval.
- **Integrations** — LangChain / LlamaIndex / Vanna shims.

## Development

```bash
pip install -e ".[dev]"
pytest          # tests require no API keys
ruff check .
mypy sqltok/
```

## License

MIT — see [LICENSE](LICENSE).
