#!/usr/bin/env python3
"""Schema-selection benchmark: BM25 baseline vs adaptive SLM router.

Compares :class:`RelevanceGreedySelector` (BM25) against
:class:`SLMSchemaRouter` on the handcrafted suite in
``benchmarks/schema_router_suite.json`` (BIRD mini-dev was unreachable from
this environment; the suite file says so explicitly).

Metric: table-level recall/precision of the selected context against the gold
table set per question, plus routing diagnostics (cheap vs escalated path,
backend actually used, tokens).

Usage:
    python benchmarks/eval_schema_router.py [--budget 1500] [--out results.json]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqltok.ddl import parse_ddl  # noqa: E402
from sqltok.select import RelevanceGreedySelector, SLMSchemaRouter  # noqa: E402
from sqltok.tokenizer import TokenCounter  # noqa: E402

SUITE = Path(__file__).resolve().parent / "schema_router_suite.json"


def evaluate(selector, questions, *, budget, counter):
    rows = []
    for item in questions:
        schema = parse_ddl(item["ddl"])
        sel = selector(schema)
        ctx = sel.select(item["q"], token_budget=budget, counter=counter, fk_expand=True)
        gold = set(item["gold"])
        picked = set(ctx.tables)
        hit = gold & picked
        rows.append(
            {
                "schema": item["schema_id"],
                "question": item["q"],
                "hard": item["hard"],
                "gold": sorted(gold),
                "picked": sorted(picked),
                "recall": len(hit) / len(gold) if gold else 1.0,
                "precision": len(hit) / len(picked) if picked else 0.0,
                "tokens": ctx.token_count,
                "n_tables": len(picked),
                "decision": getattr(sel, "decisions", [{}])[-1]
                if hasattr(sel, "decisions")
                else {},
            }
        )
    return rows


def summarize(rows):
    recalls = [r["recall"] for r in rows]
    precisions = [r["precision"] for r in rows]
    hard = [r for r in rows if r["hard"]]
    easy = [r for r in rows if not r["hard"]]
    paths: dict[str, int] = {}
    backends: dict[str, int] = {}
    for r in rows:
        d = r["decision"]
        paths[str(d.get("path", "n/a"))] = paths.get(str(d.get("path", "n/a")), 0) + 1
        backends[str(d.get("backend", "n/a"))] = backends.get(str(d.get("backend", "n/a")), 0) + 1
    return {
        "n": len(rows),
        "mean_recall": round(statistics.fmean(recalls), 3),
        "mean_precision": round(statistics.fmean(precisions), 3),
        "mean_recall_hard": round(statistics.fmean([r["recall"] for r in hard]), 3)
        if hard
        else None,
        "mean_recall_easy": round(statistics.fmean([r["recall"] for r in easy]), 3)
        if easy
        else None,
        "mean_tables": round(statistics.fmean([r["n_tables"] for r in rows]), 2),
        "mean_tokens": round(statistics.fmean([r["tokens"] for r in rows]), 1),
        "paths": paths,
        "backends": backends,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=1500)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    suite = json.loads(SUITE.read_text())
    print(f"# suite note: {suite['note']}\n")
    questions = [
        {
            "schema_id": s["id"],
            "ddl": s["ddl"],
            **q,
        }
        for s in suite["schemas"]
        for q in s["questions"]
    ]
    print(f"# {len(questions)} questions across {len(suite['schemas'])} schemas")

    counter = TokenCounter()
    arms = {
        "bm25": lambda schema: RelevanceGreedySelector(schema),
        "slm_router": lambda schema: SLMSchemaRouter(schema),
    }
    report = {}
    for arm_name, factory in arms.items():
        rows = evaluate(factory, questions, budget=args.budget, counter=counter)
        report[arm_name] = {"summary": summarize(rows), "rows": rows}
        s = report[arm_name]["summary"]
        print(f"\n## {arm_name}")
        print(
            f"   recall={s['mean_recall']} (hard={s['mean_recall_hard']}, "
            f"easy={s['mean_recall_easy']}) precision={s['mean_precision']}"
        )
        print(f"   tables/question={s['mean_tables']} tokens/question={s['mean_tokens']}")
        print(f"   paths={s['paths']} backends={s['backends']}")

    # Honest backend disclosure: which reranker actually served the escalations.
    used = report["slm_router"]["summary"]["backends"]
    print("\n# backend actually used by slm_router escalations:", used)
    print("# (no Ollama server was reachable; expect heuristic fallback)")

    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1))
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
