#!/usr/bin/env bash
# Download BIRD mini-dev (MINIDEV) into benchmarks/data/.
# The dataset is NOT committed to this repo. See https://github.com/bird-bench/mini_dev
# and https://bird-bench.github.io/ for the canonical source and terms of use.
set -euo pipefail

DATA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/data"
mkdir -p "$DATA_DIR"
cd "$DATA_DIR"

URL="https://bird-bench.oss-cn-beijing.aliyuncs.com/minidev.zip"

if [ ! -f minidev.zip ]; then
  echo "Downloading BIRD mini-dev (about 760 MB) ..."
  curl -L --connect-timeout 30 --max-time 1800 -o minidev.zip "$URL"
fi

echo "Extracting ..."
unzip -q -o minidev.zip

echo
echo "Done. The SQLite questions and databases are at:"
echo "  $DATA_DIR/minidev/MINIDEV/mini_dev_sqlite.json"
echo "  $DATA_DIR/minidev/MINIDEV/dev_databases/<db_id>/<db_id>.sqlite"
echo
echo "Run the benchmark with:"
echo "  python benchmarks/run_bird.py --provider mock \\"
echo "    --questions $DATA_DIR/minidev/MINIDEV/mini_dev_sqlite.json \\"
echo "    --db-root  $DATA_DIR/minidev/MINIDEV/dev_databases"
echo
echo "If the mirror above is unavailable, the dataset is also on Hugging Face:"
echo "  https://huggingface.co/datasets/birdsql/bird_mini_dev"
