# SQLTok benchmark results

## BIRD mini-dev, token reduction (measured)

- Dataset: BIRD mini-dev, 500 questions across 11 SQLite databases.
- Tokenizer: `tiktoken`, `cl100k_base`.
- Baseline: full schema dump (every `CREATE TABLE` plus one sample row per table).
- SQLTok: default `CoverageSelector` at budgets 1000, 2000, and 4000 tokens, one sample row per included table.
- These figures are deterministic and need no model. They were produced with the mock client, which exercises the full selection and prompt-assembly path; only the schema text differs between arms.

| arm | schema tokens (mean) | schema tokens (p95) | total input tokens | schema reduction | total input reduction |
| --- | ---: | ---: | ---: | ---: | ---: |
| baseline (full dump) | 1161 | 2961 | 629,819 | reference | reference |
| sqltok at 1000 | 497 | 876 | 298,234 | 57.2% | 52.6% |
| sqltok at 2000 | 648 | 1617 | 373,675 | 44.2% | 40.7% |
| sqltok at 4000 | 752 | 2467 | 425,687 | 35.2% | 32.4% |

Reproduce:

```bash
bash benchmarks/download.sh
python benchmarks/run_bird.py --provider mock \
  --questions benchmarks/data/minidev/MINIDEV/mini_dev_sqlite.json \
  --db-root  benchmarks/data/minidev/MINIDEV/dev_databases \
  --budgets 1000 2000 4000
```

## Execution accuracy (pending a keyed run)

Token reduction is only half the story; the claim that matters is "fewer tokens at equal accuracy." That column requires a real LLM and the official BIRD execution-accuracy script. To produce it:

```bash
export ANTHROPIC_API_KEY=...   # or OPENAI_API_KEY
python benchmarks/run_bird.py --provider anthropic --model claude-3-5-sonnet \
  --questions benchmarks/data/minidev/MINIDEV/mini_dev_sqlite.json \
  --db-root  benchmarks/data/minidev/MINIDEV/dev_databases \
  --budgets 1000 2000 4000 --in-price 3 --out-price 15
# then score each predict_*.json with benchmarks/third_party/bird_eval/
```

A 20-question `--limit 20` pass costs cents and is enough for a smoke check.

## Schema-linking recall vs BIRD gold SQL (measured, no API key)

For each of the 500 questions, the gold SQL is parsed for the tables it
references, and we check whether SQLTok kept them. Full-recall rate (all gold
tables present) is the ceiling on achievable execution accuracy: if a needed
table is dropped, no model can answer correctly.

| budget | table recall | full-recall rate | precision | avg tables |
| ---: | ---: | ---: | ---: | ---: |
| 1000 | 88.9% | 76.2% | 62.0% | 3.27 |
| 2000 | 90.8% | 80.2% | 62.2% | 3.33 |
| 4000 | 91.0% | 80.6% | 61.0% | 3.43 |

Sample-value null rate: 17.4% of columns had no sampled values (empty tables,
all-null columns, or values absent from the first sampled rows), so value
grounding has no signal for roughly one column in six.

Reproduce: `python benchmarks/eval_recall.py --questions benchmarks/data/minidev/MINIDEV/mini_dev_sqlite.json --db-root benchmarks/data/minidev/MINIDEV/dev_databases`
