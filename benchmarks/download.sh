#!/usr/bin/env bash
# Download BIRD mini-dev (MINIDEV) data into benchmarks/data/.
# The dataset is NOT committed to this repo; fetch it here.
#
# Layout produced (consumed by run_bird.py defaults):
#   benchmarks/data/questions.json
#   benchmarks/data/dev_databases/<db_id>/<db_id>.sqlite
#
# See https://github.com/bird-bench/mini_dev for the canonical source and terms.
set -euo pipefail

DATA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/data"
mkdir -p "$DATA_DIR"

echo "BIRD mini-dev is distributed by the BIRD-bench team."
echo "Download 'minidev.zip' (or 'MINIDEV') from:"
echo "  https://github.com/bird-bench/mini_dev"
echo "  https://bird-bench.github.io/"
echo
echo "Then arrange it as:"
echo "  $DATA_DIR/questions.json            # the mini_dev_sqlite.json question list"
echo "  $DATA_DIR/dev_databases/<db_id>/<db_id>.sqlite"
echo
echo "If the question file is named 'mini_dev_sqlite.json', either rename it to"
echo "questions.json or pass --questions <path> to run_bird.py."
echo
echo "This script intentionally does not auto-download to respect BIRD's terms;"
echo "follow the links above and place the files as shown."
