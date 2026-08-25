# Design of SQLTok

## The problem: Text-to-SQL token cost is the hidden bottleneck

When a large language model writes SQL from a natural-language question, it needs
the database schema in the prompt. The naive approach is to send the entire
schema: every `CREATE TABLE` plus a few sample rows. On a warehouse with
thousands of tables this routinely produces prompts of fifty thousand tokens or
more. That is expensive to serve, slow to generate, and less accurate, because
the model has to find the few relevant tables inside a wall of irrelevant ones.

The problem is not that models are bad at SQL. It is that the schema context is
the wrong shape. SQLTok exists to make the schema context the right shape: only
the tables and columns the question actually needs, within a hard token budget,
and guaranteed to be joinable.

## The gap SQLTok fills

Most existing schema retrieval for Text-to-SQL is top-k keyword matching. That
fails in three specific ways that SQLTok is designed to handle.

| Limitation of keyword retrieval | How SQLTok handles it |
| --- | --- |
| Mentions hide in cell values. "France" is a value in `customers.country`, never a column name, so keyword search over names misses it. | Native value grounding with MinHash and banded LSH over sampled cell values. |
| Top-k ignores the budget and redundancy. It can exceed the token ceiling or select several tables covering the same content. | Submodular coverage under a hard token budget, where diminishing returns remove redundancy and yield a `(1 - 1/e)` approximation guarantee. |
| Retrieved tables may not be joinable. Two relevant tables with no foreign-key path lead the model to invent joins. | Foreign-key Steiner connectivity adds the minimal set of bridge tables. |

BM25 is retained as the baseline selector (`RelevanceGreedySelector`) so that
benchmark gains are attributable. The default selector is the value-grounded
submodular algorithm described in this document.

## How SQLTok fits in the SQL tooling ecosystem

SQLTok is a library, not a framework. It does one thing: turn a schema, a
question, and a budget into a compact, joinable schema string. It has no LLM
client, no framework adapter, and no network I/O in the core. It plugs into any
Text-to-SQL pipeline as a pre-processing step.

The output is a plain-text `CREATE TABLE`-style string. That means it works with
every model, every framework, and every prompt template. It is compatible with
LangChain, LlamaIndex, Vanna, and any custom pipeline. The token budget is
measured with `tiktoken`, which is the same tokenizer used by OpenAI's models,
so the budget is meaningful for the target model without translation.

The benchmark harness is built around BIRD, the de facto standard
Text-to-SQL benchmark. SQLTok's gains are measured against the BIRD mini-dev
split (500 questions, 11 databases) using the official execution-accuracy script.
This makes results comparable to other schema-retrieval work.

## Architecture overview

SQLTok has four stages.

```
question, schema, budget
        |
        v
  Stage 1: Value grounding
  (MinHash + LSH over names and sampled values)
        |
        v
  Stage 2: Submodular budgeting
  (CELF greedy under a hard token budget)
        |
        v
  Stage 3: FK Steiner connectivity
  (add bridge tables so the selection is joinable)
        |
        v
  Stage 4: Budget guarantee
  (re-measure with tiktoken at every step)
        |
        v
  compact CREATE TABLE string
```

### Stage 1: Value grounding

The goal is a matrix `cover[table, mention]` in the range zero to one, plus a
weight for each mention.

1. **Mention extraction** (`grounding/text.py`). The question is split into
   candidate phrases: one to three word n-grams plus quoted literals, with
   stopwords trimmed from the edges. "total revenue by region" yields "total
   revenue", "revenue", and "region".

2. **Character shingling**. Each string becomes a set of three-character
   substrings. "France" becomes `{fra, ran, anc, nce}`. Character shingles give
   fuzzy matching robust to plurals, casing, and small typos, so "widgets" and
   "widget" share most of their shingles.

3. **MinHash** (`grounding/minhash.py`). Each shingle set is reduced to a
   signature of length 64. The probability that two sets share the same minimum
   hash in a given position equals their Jaccard similarity:

   ```
   P(min h_i(A) = min h_i(B)) = |A intersect B| / |A union B| = Jaccard(A, B)
   ```

   The fraction of equal signature positions is an unbiased estimate of Jaccard
   similarity, computed by comparing two vectors of 64 integers instead of two
   raw sets. Fixed seeds make this deterministic.

4. **Banded LSH** (`grounding/lsh.py`). Every schema string (table names, column
   names, sampled cell values) is indexed by its signature, split into 32 bands
   of 2 rows. Items that match across a full band fall into the same bucket, and
   a query inspects only colliding buckets. This produces candidates in near
   constant time rather than scanning every value. The collision threshold is
   approximately `(1 / bands) ** (1 / rows)`, about 0.18, which favours recall.

5. **Affinity and self-supervised IDF** (`grounding/affinity.py`). For each
   mention, the best estimated Jaccard match per table becomes an entry of
   `cover`. Each mention is then weighted by an inverse document frequency
   learned from the schema itself:

   ```
   weight(m) = log(1 + num_tables / df(m))
   ```

   where `df(m)` is the number of tables the mention touches. A mention that hits
   every table, such as `id` or `name`, carries close to zero weight, while a
   mention that hits a single table is highly discriminative. The signal comes
   from the database, not from a generic English corpus.

### Stage 2: Submodular budgeting

The objective (`select/coverage.py`) is weighted maximum coverage:

```
f(S) = sum over mentions m of  weight(m) * max over tables T in S of cover(m, T)
```

Each mention scores through the single best table that covers it. The use of
`max` gives diminishing returns: once a mention is covered, another table that
covers it adds zero marginal value, so redundancy is handled automatically and
`f` is monotone and submodular. For such functions, the greedy maximizer has the
classic `(1 - 1/e)`, about 0.63, approximation guarantee.

Tables have different token costs, so selection is a knapsack. At each step
SQLTok picks the table that maximizes marginal gain divided by token cost, which
is the token-budgeted, redundancy-aware rule from AdaGReS, and commits it only
if the re-measured context still fits the budget.

Because marginal gains only decrease as tables are added, a CELF lazy evaluation
keeps a priority queue and recomputes a candidate only when it reaches the top,
which reduces hundreds of evaluations to a few and is the part that scales to
wide schemas.

Ratio-greedy can be misled by a single large high-value table, so SQLTok also
compares against the best single table that fits, following Khuller, Moss, and
Naor, and keeps whichever covers more. If nothing grounds, it packs the smallest
tables first so the output is never empty and is always within budget.

### Stage 3: Foreign-key Steiner connectivity

A relevance-only set can contain `products` and `orders` with no direct join,
which leads the model to invent an incorrect join. SQLTok (`select/connect.py`)
builds the undirected foreign-key graph, checks whether the selected tables form
one connected component, and if not finds the shortest foreign-key path between
components and adds the minimal bridge tables, for example `line_items`
connecting `products` and `orders`, as long as the budget allows. This is a
heuristic Steiner tree over the foreign-key graph, following the AutoLink
observation that foreign keys are the natural bridges between relevant tables.

### Stage 4: The budget guarantee

Every tentative add (`select/base.py`, `BudgetPacker.try_add`) renders the full
context and counts it with `tiktoken`, committing a table only if the total stays
within budget, and falling back to dropping the sample row before dropping the
table. Because the actual string is measured at every step, `token_count` at or
below `token_budget` is an invariant that no selection logic can break.

## Design decisions and alternatives considered

### Why MinHash and LSH instead of embeddings?

Embeddings (e.g. sentence-transformers) are powerful but heavy: they require
loading a model, sending text through it, and storing dense vectors. MinHash + LSH
is implemented in pure Python and NumPy, has no network or model dependency, and
is deterministic with fixed seeds. The tradeoff is that LSH is approximate, but
the banded scheme with threshold ~0.18 favours recall, which is the correctness
metric. Embeddings are available as an optional extra (`sqltok[embeddings]`) in
the BM25 retriever for hybrid retrieval, but the default selector does not need
them.

### Why submodular coverage instead of pure BM25 top-k?

Top-k keyword matching has no notion of budget or redundancy. It can select five
tables all covering the same keyword, exceed the token ceiling, or miss tables
whose names contain no keywords but whose values do. Submodular coverage gives a
provable approximation guarantee `(1 - 1/e)` and automatically handles
redundancy. The knapsack variant with CELF lazy evaluation keeps the per-step
cost low.

### Why BM25 as the baseline instead of a weaker method?

BM25 is the standard lexical retriever. It is simple, fast, and well-understood.
Keeping it as a named baseline means benchmark gains are attributable to the
grounding and coverage machinery, not to a straw-man retriever. The gap between
`RelevanceGreedySelector` and `CoverageSelector` on BIRD mini-dev is the
measurable effect of the new algorithm.

### Why hard token budget instead of soft or estimated?

LLM providers charge by token and models have hard context windows. A heuristic
like "len(text) / 4" can be off by 2x or more, which breaks both cost models and
context limits. SQLTok measures every candidate context with the real tokenizer
before committing it, so the budget is a hard invariant.

### Why FK connectivity instead of letting the model join?

A model asked to join two tables with no foreign-key path will invent a join
condition, which is wrong. Adding bridge tables costs a few extra tokens but
prevents hallucinated joins. The heuristic Steiner tree over the foreign-key
graph is the minimal addition subject to the budget.

### Why Python and NumPy instead of Rust from the start?

The v0.1 core is Python and NumPy because the research was exploratory: the
algorithm, the LSH parameters, and the FK-expansion policy all needed to be
tuned on real data. Rust is the right next step for speed and distribution once
the algorithm is frozen, and there is a detailed plan for that migration.

## Performance characteristics

On BIRD mini-dev (500 questions, 11 SQLite databases), measured with `tiktoken`
(`cl100k_base`). Baseline is the full schema dump with one sample row per table.

### Schema-linking recall

| Budget | Table recall | Full-recall rate | Precision | Avg tables |
| ---: | ---: | ---: | ---: | ---: |
| 1000 | 96.3% | 91.8% | 42.8% | 5.45 |
| 2000 | 99.0% | 97.4% | 40.7% | 6.11 |
| 4000 | 99.0% | 97.4% | 39.8% | 6.24 |

Full-recall is the rate at which every gold-query table survives selection, which
is the ceiling on achievable execution accuracy.

### Token reduction

| Arm | Schema tokens (mean) | Total input tokens | Total input reduction |
| --- | ---: | ---: | ---: |
| Baseline (full dump) | 1161 | 629,819 | Reference |
| SQLTok at 1000 | 703 | 401,285 | 36.3% |
| SQLTok at 2000 | 944 | 521,760 | 17.2% |
| SQLTok at 4000 | 1064 | 581,559 | 7.7% |

### Honest reading

- Budget 2000 is the sweet spot on this suite: 97.4% full-recall at 17% fewer
  total prompt tokens. Budget 1000 trades recall (91.8%) for larger savings (36%).
- The token reduction looks modest because BIRD schemas are small (the full dump
  averages only 1161 tokens). The method's token savings grow with schema size,
  since the baseline scales with the database while SQLTok stays at the budget.
- Precision is around 40% because FK-neighbour expansion deliberately spends
  spare budget on likely join targets. Set `CoverageSelector(schema,
  fk_min_links=2)` to favour precision and tokens over recall: that yields
  roughly 81 to 86% full-recall at 553 to 819 mean tokens.
- Sample-value null rate: 17.4% of columns had no sampled values (empty tables,
  all-null columns, or values absent from the first sampled rows), so value
  grounding has no signal for roughly one column in six.

### Speed

Grounding dominates the per-question cost. The LSH index is built once per
schema in `SchemaGrounding.__init__`. For a 100-table schema with ~20 strings
per table, the index occupies roughly 1 MB. `ground(question)` is near-constant
time. `CoverageSelector.select` is `O(T log T)` where T is the number of
candidate tables, dominated by CELF heap operations. On BIRD mini-dev, the full
500-question recall eval (`eval_recall.py`) runs in under a minute on a laptop.

## Future directions

### v0.2 roadmap

1. SID semantic cache. Canonicalize natural language and SQL into a hashable SQL
   Intent Descriptor, with exact and derivation (roll-up and filter-down) cache
   hits.
2. Intent canonicalizer. Convert a SQL AST to a SID with `sqlglot`, and convert
   natural language to a SID with confidence gating.
3. Invalidation tag registry. Provide and invalidate cache entries by table
   lineage, in the style of RTK Query.
4. Cache backends. Add Redis and DuckDB, and align the KV prefix for provider
   prompt caches.
5. Additional selectors. A cross-encoder rerank selector and an LLM agentic
   selector in the style of Datalake Agent and AutoLink, plus embedding hybrid
   retrieval.
6. Integrations. Adapters for LangChain, LlamaIndex, and Vanna.

### Rust migration

The Rust rewrite plan is documented in [`rust-rewrite-plan.md`](rust-rewrite-plan.md).
The short version: port the hot, well-specified core to a Rust crate and expose
it through the existing `pip install sqltok` API with a PyO3 wheel, while keeping
the current Python implementation as the oracle until parity is proven on BIRD.

What Rust buys:
- Speed on the selection and grounding loop, which is the part that must scale
  to wide warehouse schemas with thousands of tables.
- Single static binary distribution and a real crate for the Rust data ecosystem
  (DataFusion, Polars, sqlparser are all Rust).
- Memory safety and fearless concurrency for batch and serving use.

What Rust does not buy:
- Better recall or accuracy. Those are algorithmic and live in the design, not
  the language. The recent jump from 78 to 97 percent full-recall came from the
  FK-expansion algorithm, not from any language feature.
- Any benefit for the LLM clients or the BIRD harness. Those stay in Python.

The migration is phased and de-risked by differential testing. The current
Python implementation is the oracle. No swap happens until the Rust core
produces the same selected tables and the same token counts on BIRD, within a
documented tolerance.

### Mature SQL practices

The SQL thread of the Rust plan includes:
- Dialect-aware parsing with explicit dialects (SQLite, Postgres, MySQL,
  Snowflake) rather than one permissive parser.
- Catalog-based introspection: `information_schema` for Postgres and MySQL,
  `PRAGMA` for SQLite.
- Handle composite foreign keys, views, generated columns, and column comments
  and descriptions pulled from the catalog.
- Type-aware value sampling: reservoir sampling or `TABLESAMPLE` where available,
  explicit NULL handling, and large-value truncation.
- Deterministic, dialect-correct DDL rendering for the prompt.

## References

SQLTok packages and combines techniques from recent work. If you build on it,
please credit these sources.

Foundations of the library:

1. Datalake Agent. Agentic NL2SQL to Reduce Computational Costs. arXiv
   [2510.14808](https://arxiv.org/abs/2510.14808). Budget-aware lazy schema
   discovery, up to 87 percent token reduction.
2. OLAP Intent Signature, LLMSigCache. Semantic Caching for OLAP via LLM-Based
   Query Canonicalization, DOLAP 2026. arXiv
   [2602.19811](https://arxiv.org/abs/2602.19811). The intent-signature cache
   that the v0.2 SID layer generalizes.
3. AgentSM. Semantic Memory for Agentic Text-to-SQL. arXiv
   [2601.15709](https://arxiv.org/abs/2601.15709). Reasoning-path reuse for the
   v0.2 memory and derivations roadmap.

Sources that inform the default selector:

4. Bidirectional Schema Linking. Findings of EACL 2026. arXiv
   [2510.14296](https://arxiv.org/abs/2510.14296). Schema linking as a
   first-class retrieval problem.
5. AutoLink. Autonomous Schema Exploration and Expansion at Scale. arXiv
   [2511.17190](https://arxiv.org/abs/2511.17190). Foreign keys as natural
   bridges, which motivates Steiner connectivity.
6. AdaGReS. Adaptive Greedy Context Selection via Redundancy-Aware Scoring for
   Token-Budgeted RAG. arXiv [2512.25052](https://arxiv.org/abs/2512.25052).
   The token-budgeted greedy rule.
7. Sub-SA. Submodular Selective Annotation. arXiv
   [2407.05693](https://arxiv.org/abs/2407.05693). Submodular reward and
   diversity selection.
8. CHESS. Contextual Harnessing for Efficient SQL Synthesis. arXiv
   [2405.16755](https://arxiv.org/abs/2405.16755). LSH value grounding.

Classical results behind the mathematics: Broder, On the resemblance and
containment of documents, 1997 (MinHash); Indyk and Motwani, 1998 (LSH);
Nemhauser, Wolsey, and Fisher, 1978 (the `(1 - 1/e)` bound); Khuller, Moss, and
Naor, 1999 (budgeted maximum coverage); Leskovec et al., Cost-effective
Outbreak Detection, 2007 (CELF).
