# SQLTok benchmark results

Dataset: BIRD mini-dev, 500 questions across 11 SQLite databases. Tokenizer:
`tiktoken`, `cl100k_base`. Baseline: full schema dump with one sample row per
table. SQLTok: default `CoverageSelector` (value grounding, submodular coverage,
FK-neighbour expansion, FK-Steiner connectivity) at budgets 1000, 2000, 4000.

All numbers below are deterministic and need no model. Execution accuracy needs a
keyed run and is pending.

## Schema-linking recall vs BIRD gold SQL

For each question the gold SQL is parsed for the tables it references, and we
check whether SQLTok kept them. Full-recall (all gold tables present) is the
ceiling on achievable execution accuracy: if a needed table is dropped, no model
can answer correctly.

| budget | table recall | full-recall rate | precision | avg tables |
| ---: | ---: | ---: | ---: | ---: |
| 1000 | 96.3% | 91.8% | 42.8% | 5.45 |
| 2000 | 99.0% | 97.4% | 40.7% | 6.11 |
| 4000 | 99.0% | 97.4% | 39.8% | 6.24 |

Reproduce: `python benchmarks/eval_recall.py --questions benchmarks/data/minidev/MINIDEV/mini_dev_sqlite.json --db-root benchmarks/data/minidev/MINIDEV/dev_databases`

## Token reduction

| arm | schema tokens (mean) | schema tokens (p95) | total input tokens | total input reduction |
| --- | ---: | ---: | ---: | ---: |
| baseline (full dump) | 1161 | 2961 | 629,819 | reference |
| sqltok at 1000 | 703 | 993 | 401,285 | 36.3% |
| sqltok at 2000 | 944 | 1698 | 521,760 | 17.2% |
| sqltok at 4000 | 1064 | 2879 | 581,559 | 7.7% |

Reproduce: `python benchmarks/run_bird.py --provider mock --questions benchmarks/data/minidev/MINIDEV/mini_dev_sqlite.json --db-root benchmarks/data/minidev/MINIDEV/dev_databases`

## Reading these numbers honestly

- Budget 2000 is the sweet spot on this suite: 97.4% full-recall at 17% fewer
  total prompt tokens. Budget 1000 trades recall (91.8%) for larger savings (36%).
- The token reduction looks modest because BIRD schemas are small (the full dump
  averages only 1161 tokens). The method's token savings grow with schema size,
  since the baseline scales with the database while SQLTok stays at the budget.
  Recall is the transferable correctness metric and does not depend on schema size.
- Precision is around 40% because FK-neighbour expansion deliberately spends
  spare budget on likely join targets. Set `CoverageSelector(schema, fk_min_links=2)`
  to favour precision and tokens over recall: that yields roughly 81 to 86%
  full-recall at 553 to 819 mean tokens.
- Sample-value null rate: 17.4% of columns had no sampled values (empty tables,
  all-null columns, or values absent from the first sampled rows), so value
  grounding has no signal for roughly one column in six.

## Execution accuracy (run it free, no API key)

Token and recall numbers do not prove the model answers correctly. That needs a
real LLM and the official BIRD execution-accuracy script. You can do this with no
OpenAI or Anthropic key using a local model through Ollama:

```bash
# one-time: install Ollama, then pull a coding model
ollama pull qwen2.5-coder:7b

python benchmarks/run_bird.py --provider ollama --model qwen2.5-coder:7b \
  --questions benchmarks/data/minidev/MINIDEV/mini_dev_sqlite.json \
  --db-root  benchmarks/data/minidev/MINIDEV/dev_databases \
  --budgets 1000 2000 4000
# then score each predict_*.json with benchmarks/third_party/bird_eval/
```

Hosted providers work the same way if you prefer (`--provider anthropic` or
`--provider openai`, reading the usual env keys), but they are optional. The
local path costs nothing.

## Execution-grounded evaluation battery (#43)

`python benchmarks/eval_execution.py --data-dir benchmarks/sample_data`
(mock LLM, offline, deterministic). The battery governance-checks every
generated query, runs it in a read-only budgeted sandbox, and compares the
result against the trusted reference query.

| signal | measured |
| --- | --- |
| execution success rate | 100.0% (mock emits canned `SELECT 1;`) |
| null-result rate | 0.0% |
| semantic equivalence vs gold | 4× `row_content_mismatch`, 1× `equivalent` |
| governance verdicts | 5× `allow` |
| questions with full table scan | 0 (the mock's canned `SELECT 1;` reads no tables; the plan pseudo-step `SCAN CONSTANT ROW` is excluded from the signal by construction) |

The single `equivalent` is a documented degenerate case, not a success:
question 4's gold is `COUNT(*) = 1` on this fixture, whose 1×1 result `[(1,)]`
coincides with the mock's `SELECT 1`. Execution-based equivalence has known
false positives on tiny fixtures.

| budget | recall | precision | full-recall | fk-recall (n) | latency |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1000 | 100.0% | 60.0% | 100.0% | 100.0% (3) | 2.7 ms |
| 2000 | 100.0% | 60.0% | 100.0% | 100.0% (3) | 2.0 ms |

Repair arm (synthetic fixture — a scripted generator emitting one broken query
then the gold query; measures loop mechanics, not model ability):
repair success 100.0%, mean attempts 2.00, escalation 0.0%, unhandled 0.0%.

Adversarial governance battery: 11/11 pinned cases behave as expected
(stacked `DROP TABLE`, UNION exfiltration, DML smuggling, case-evasion,
unparseable input blocked; benign reads allowed).

Reproduce: `python benchmarks/eval_execution.py --data-dir benchmarks/sample_data`
