# SQLTok benchmark harness (BIRD mini-dev)

Compares two ways of feeding schema to an LLM, holding the model and prompt
template fixed and varying **only** the schema context:

- **baseline**, full schema dump (every `CREATE TABLE` + 1 sample row/table).
- **sqltok**, `SchemaBudgetManager` output at token budgets 1000 / 2000 / 4000.

## Smoke run (no API keys, free)

A tiny committed fixture (`sample_data/`, *not* BIRD) lets you exercise the whole
pipeline with a mock LLM that echoes canned SQL:

```bash
python benchmarks/make_sample_data.py          # regenerate the fixture (optional)
python benchmarks/run_bird.py --provider mock \
    --data-dir benchmarks/sample_data --limit 5
```

This writes `benchmarks/results/results.md`, `per_question.jsonl`, and one
`predict_<arm>.json` per arm. Execution accuracy is `n/a` for the mock (it does
not answer correctly by design); the run verifies prompt construction, token
accounting, caching, and outputs.

## Real run (BIRD mini-dev, 500 questions)

1. Fetch the dataset (not committed): `bash benchmarks/download.sh` and follow
   the instructions to place `benchmarks/data/questions.json` and
   `benchmarks/data/dev_databases/<db_id>/<db_id>.sqlite`.
2. Run with a local model through Ollama, which needs no API key and costs
   nothing:

   ```bash
   ollama pull qwen2.5-coder:7b
   python benchmarks/run_bird.py --provider ollama --model qwen2.5-coder:7b \
       --questions benchmarks/data/minidev/MINIDEV/mini_dev_sqlite.json \
       --db-root  benchmarks/data/minidev/MINIDEV/dev_databases \
       --budgets 1000 2000 4000
   ```

   Hosted providers are optional (`--provider anthropic` or `--provider openai`,
   reading `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`, add `--in-price`/`--out-price`
   for cost estimates). Responses are cached under `benchmarks/.llm_cache/`
   (keyed by hash of prompt+model), so reruns are free and resumable. Use
   `--limit 20` for a quick smoke test against the real data.
3. Score execution accuracy with BIRD's **official** script, see
   `third_party/bird_eval/README.md`, and paste the numbers into
   `results/results.md`.

## Flags

`--provider {mock,ollama,anthropic,openai}`, `--model`, `--budgets ...`,
`--no-baseline`, `--limit N`, `--sample-rows`, `--encoding`,
`--in-price/--out-price`, `--data-dir/--questions/--db-root/--out-dir/--cache-dir`.
