# Vendored BIRD execution-accuracy evaluation

SQLTok does **not** ship a homemade SQL-equivalence checker. Execution accuracy
must be scored with BIRD's **official** evaluation script, which compares the
*executed result sets* of predicted vs. gold SQL against the SQLite databases.

## Fetch the official script

The script is `evaluation_ex.py` (a.k.a. `evaluation.py`) from the BIRD mini-dev
repository:

- Source: https://github.com/bird-bench/mini_dev (directory `evaluation/`)
- License: the BIRD-bench repository's license (MIT at time of writing). When you
  vendor the file, **copy its `LICENSE` here** alongside it so attribution is
  preserved. This directory is otherwise git-ignored (see `.gitignore`) so the
  third-party code is not committed without its license.

```bash
# from the repo root, with the BIRD repo checked out somewhere:
cp /path/to/mini_dev/evaluation/evaluation_ex.py benchmarks/third_party/bird_eval/
cp /path/to/mini_dev/LICENSE                       benchmarks/third_party/bird_eval/
```

## Run it

`run_bird.py` writes one BIRD-format predictions file per arm, e.g.
`benchmarks/results/predict_baseline.json` and
`benchmarks/results/predict_sqltok_2000.json`. Feed each to the official script
(flags mirror BIRD's runner; consult the script's `--help`):

```bash
python benchmarks/third_party/bird_eval/evaluation_ex.py \
    --predicted_sql_path benchmarks/results/predict_sqltok_2000.json \
    --ground_truth_path  benchmarks/data/                            \
    --db_root_path       benchmarks/data/dev_databases/              \
    --diff_json_path     benchmarks/data/questions.json
```

Paste the reported execution accuracy into the `exec acc` column of
`benchmarks/results/results.md` for each arm.
