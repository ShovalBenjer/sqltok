#!/usr/bin/env python3
"""Schema-linking recall evaluation against BIRD gold SQL (no API key needed).

For each question, parse the gold SQL for the tables it references, then check
whether SQLTok's selected schema keeps them. This measures the load-bearing
property: if a required table is missing from the context, the model cannot
write a correct query, no matter how good it is.

Metrics, per token budget:
- table recall: fraction of gold tables included, averaged over questions.
- full-recall rate: fraction of questions where ALL gold tables are included.
  This is the ceiling on achievable execution accuracy.
- precision: fraction of selected tables that are gold tables.
- avg tables: mean number of tables selected.

Usage:
    python benchmarks/eval_recall.py \\
        --questions benchmarks/data/minidev/MINIDEV/mini_dev_sqlite.json \\
        --db-root  benchmarks/data/minidev/MINIDEV/dev_databases
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sqlglot
from sqlglot import exp

from sqltok import SchemaBudgetManager


def gold_tables(sql: str, valid: set[str]) -> set[str]:
    try:
        names = {t.name.lower() for t in sqlglot.parse_one(sql, read="sqlite").find_all(exp.Table)}
    except Exception:
        return set()
    return {n for n in names if n in valid}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--questions", required=True)
    p.add_argument("--db-root", required=True)
    p.add_argument("--budgets", type=int, nargs="+", default=[1000, 2000, 4000])
    args = p.parse_args()

    questions = json.loads(Path(args.questions).read_text())
    db_root = Path(args.db_root)

    mgrs: dict[str, SchemaBudgetManager] = {}
    agg = {b: {"recall": [], "full": 0, "prec": [], "ntab": []} for b in args.budgets}
    null_cols = total_cols = scored = 0

    for q in questions:
        db = q["db_id"]
        if db not in mgrs:
            mgrs[db] = SchemaBudgetManager.from_sqlite(db_root / db / f"{db}.sqlite", sample_rows=3)
            for t in mgrs[db].schema.tables.values():
                for c in t.columns:
                    total_cols += 1
                    null_cols += 0 if c.sample_values else 1
        mgr = mgrs[db]
        valid = {t.lower() for t in mgr.schema.table_names()}
        gt = gold_tables(q["SQL"], valid)
        if not gt:
            continue
        scored += 1
        for b in args.budgets:
            sel = {t.lower() for t in mgr.build_context(q["question"], token_budget=b).tables}
            hit = len(gt & sel)
            agg[b]["recall"].append(hit / len(gt))
            agg[b]["full"] += 1 if gt <= sel else 0
            agg[b]["prec"].append(hit / len(sel) if sel else 0.0)
            agg[b]["ntab"].append(len(sel))

    print(f"scored questions: {scored}/{len(questions)}  databases: {len(mgrs)}")
    print(f"sample-value null rate: {null_cols}/{total_cols} = {100*null_cols/total_cols:.1f}%")
    print(f"\n{'budget':>7} | {'recall':>7} | {'full-recall':>11} | {'precision':>9} | {'avg tables':>10}")
    for b in args.budgets:
        r = agg[b]
        print(f"{b:>7} | {100*st.mean(r['recall']):>6.1f}% | {100*r['full']/scored:>10.1f}% | "
              f"{100*st.mean(r['prec']):>8.1f}% | {st.mean(r['ntab']):>10.2f}")


if __name__ == "__main__":
    main()
