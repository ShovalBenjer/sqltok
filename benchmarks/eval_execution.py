#!/usr/bin/env python3
"""Execution-grounded Text2SQL evaluation battery (#43).

Runs the full eval discipline from the issue over the sample fixture
(offline, deterministic, no API keys with ``--provider mock``):

* retrieval: recall AND precision, full-recall rate, FK coverage, latency
  per token budget (the under/over-retrieval distinction);
* execution: every generated query is governance-checked, then run in a
  read-only budgeted sandbox — execution success rate, null-result frequency,
  runtime exceptions. Note: governance is a recorded parallel signal in the
  battery, not an execution gate — the sandbox runs the query regardless
  (read-only + budgeted), so the battery measures what a blocked query would
  have done too (defense-in-depth measurement);
* semantic equivalence: generated result vs trusted reference result;
* repair: a synthetic scripted generator (clearly labeled) exercises the
  repair loop mechanics — repair success rate, attempts, escalation fallback;
* governance: the adversarial battery pins the attack surface.

Writes ``benchmarks/results/eval_execution.json`` and prints a summary table.

Example::

    python benchmarks/eval_execution.py --data-dir benchmarks/sample_data
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_recall import gold_tables  # noqa: E402
from llm import build_client  # noqa: E402

from sqltok import (  # noqa: E402
    AccessPolicy,
    EscalationEvidence,
    EscalationPolicy,
    RepairLoop,
    SandboxExecutor,
    SchemaBudgetManager,
    govern,
    introspect_sqlite,
    measure_retrieval,
    repair_metrics,
    resolve_scan_tables,
    run_battery,
    semantic_equivalence,
)

SYSTEM_PROMPT = (
    "You are an expert SQLite analyst. Given a database schema and a question, "
    "write ONE valid SQLite query that answers it. Return only the SQL, with no "
    "explanation and no markdown fences."
)
PROMPT_TEMPLATE = "Database schema:\n{schema}\n\nQuestion: {question}\n\nSQLite query:"


@dataclass
class _ScriptedGenerator:
    """Synthetic repair fixture: broken query once, then the gold query.

    Measures repair-loop mechanics (feedback threading, success accounting,
    escalation fallback) — not any real model's repair ability.
    """

    scripts: dict[int, str]
    fallback: str
    calls: int = 0

    def __call__(self, prompt_text: str, last_error: str | None) -> str:
        self.calls += 1
        return self.scripts.get(self.calls, self.fallback)


@dataclass
class BatteryTotals:
    """Aggregate counters over the whole battery run."""

    n_questions: int = 0
    exec_ok: int = 0
    exec_errors: Counter[str] = field(default_factory=Counter)
    null_results: int = 0
    equivalence: Counter[str] = field(default_factory=Counter)
    governance: Counter[str] = field(default_factory=Counter)
    full_scans: int = 0
    retrieval: dict[str, dict[str, float | int | None]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "n_questions": self.n_questions,
            "execution_success_rate": self.exec_ok / self.n_questions if self.n_questions else 0.0,
            "null_result_rate": self.null_results / self.n_questions if self.n_questions else 0.0,
            "execution_errors": dict(self.exec_errors),
            "equivalence": dict(self.equivalence),
            "governance": dict(self.governance),
            "questions_with_full_scan": self.full_scans,
            "retrieval_per_budget": self.retrieval,
        }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", default="benchmarks/sample_data")
    p.add_argument("--provider", default="mock")
    p.add_argument("--model", default="mock-1")
    p.add_argument("--budgets", type=int, nargs="+", default=[1000, 2000])
    p.add_argument("--out", default="benchmarks/results/eval_execution.json")
    p.add_argument("--max-repair-attempts", type=int, default=3)
    args = p.parse_args()

    data_dir = Path(args.data_dir)
    questions_path = data_dir / "questions.json"
    if not questions_path.exists():
        raise SystemExit(
            f"no {questions_path}: run from the repo root with --data-dir benchmarks/sample_data"
        )
    questions = json.loads(questions_path.read_text())
    client = build_client(args.provider, args.model)
    policy = AccessPolicy()
    totals = BatteryTotals(n_questions=len(questions))
    repair_reports = []
    per_question: list[dict[str, object]] = []

    schemas: dict[str, object] = {}
    managers: dict[str, SchemaBudgetManager] = {}
    executors: dict[str, SandboxExecutor] = {}

    for q in questions:
        db_id: str = q["db_id"]
        if db_id not in schemas:
            db_path = data_dir / "dev_databases" / db_id / f"{db_id}.sqlite"
            schema = introspect_sqlite(db_path)
            schemas[db_id] = schema
            managers[db_id] = SchemaBudgetManager(schema)
            executors[db_id] = SandboxExecutor(db_path)
        schema = schemas[db_id]
        executor = executors[db_id]
        valid_tables = {t.name.lower() for t in schema.tables.values()}
        gold_sql: str = q["SQL"]
        gtables = gold_tables(gold_sql, valid_tables)
        # Required FK edges: pairs of gold tables joined by a declared FK.
        fk_pairs: set[tuple[str, str]] = set()
        for table in schema.tables.values():
            for fk in table.foreign_keys:
                a, b = table.name.lower(), fk.ref_table.lower()
                if a in gtables and b in gtables:
                    fk_pairs.add((a, b))

        qrec: dict[str, object] = {"question_id": q["question_id"], "db_id": db_id}
        for budget in args.budgets:
            start = time.perf_counter()
            ctx = managers[db_id].build_context(q["question"], token_budget=budget)
            latency_ms = (time.perf_counter() - start) * 1000.0
            rep = measure_retrieval(
                selected=ctx.tables,
                gold_tables=gtables,
                required_fks=sorted(fk_pairs),
                latency_ms=latency_ms,
            )
            key = f"budget_{budget}"
            agg = totals.retrieval.setdefault(
                key,
                {
                    "recall": 0.0,
                    "precision": 0.0,
                    "full_recall": 0.0,
                    "fk_recall": 0.0,
                    "latency_ms": 0.0,
                    "n": 0.0,
                    "n_fk": 0.0,
                },
            )
            agg["recall"] += rep.recall
            agg["precision"] += rep.precision
            agg["full_recall"] += 1.0 if rep.full_recall else 0.0
            if rep.fk_recall is not None:
                agg["fk_recall"] += rep.fk_recall
                agg["n_fk"] += 1.0
            agg["latency_ms"] += rep.latency_ms
            agg["n"] += 1.0
            qrec[key] = asdict(rep)

        # Generation (mock provider: canned SQL — the battery measures the
        # harness honestly; execution accuracy with the mock is meaningless
        # by design, see benchmarks/llm/mock.py).
        prompt = PROMPT_TEMPLATE.format(
            schema=managers[db_id]
            .build_context(q["question"], token_budget=max(args.budgets))
            .text,
            question=q["question"],
        )
        generated = client.complete(SYSTEM_PROMPT, prompt).text.strip()

        gov = govern(generated, policy, executor)
        totals.governance[gov.verdict.value] += 1
        qrec["governance"] = gov.verdict.value

        gen_out = executor.execute(generated)
        gold_out = executor.execute(gold_sql)
        if gen_out.ok:
            totals.exec_ok += 1
            if gen_out.is_empty:
                totals.null_results += 1
            if gen_out.full_scan_tables:
                totals.full_scans += 1
        else:
            totals.exec_errors[gen_out.error_class or "unknown"] += 1
        equiv = semantic_equivalence(gen_out, gold_out, gold_sql=gold_sql)
        totals.equivalence[equiv.verdict.value] += 1
        qrec["execution_ok"] = gen_out.ok
        qrec["equivalence"] = equiv.verdict.value
        qrec["full_scan_tables"] = list(resolve_scan_tables(generated, gen_out.full_scan_tables))

        # Repair arm — SYNTHETIC fixture (see _ScriptedGenerator).
        broken = gold_sql.replace("SELECT", "SELEC", 1)
        generate = _ScriptedGenerator(scripts={1: broken, 2: gold_sql}, fallback=gold_sql)
        loop = RepairLoop(
            executor,
            generate,
            max_attempts=args.max_repair_attempts,
            escalation_policy=EscalationPolicy(),
        )
        evidence = EscalationEvidence(
            mention_count=2,
            tables_selected=len(gtables),
            covered_weight=1.0,
            top_scores=(0.9, 0.8),
        )
        repair_reports.append(loop.run(q["question"], prompt, escalation_evidence=evidence))
        qrec["repair_attempts"] = repair_reports[-1].attempts_used
        qrec["repaired"] = repair_reports[-1].repaired
        per_question.append(qrec)

    for agg in totals.retrieval.values():
        n = agg.pop("n")
        n_fk = agg.pop("n_fk")
        for k in ("recall", "precision", "full_recall", "latency_ms"):
            agg[k] = agg[k] / n if n else 0.0
        agg["fk_recall"] = agg["fk_recall"] / n_fk if n_fk else None
        agg["fk_questions"] = int(n_fk)

    battery = run_battery(AccessPolicy(name="strict", restricted_tables=("restricted_pii",)))
    rm = repair_metrics(repair_reports)

    payload = {
        "provider": args.provider,
        "model": args.model,
        "budgets": args.budgets,
        "totals": totals.as_dict(),
        "repair_metrics": asdict(rm),
        "repair_note": (
            "SYNTHETIC fixture: scripted generator (broken once, then gold). "
            "Measures repair-loop mechanics, not model ability."
        ),
        "adversarial_battery": {
            "passed": battery.passed,
            "total": battery.total,
            "cases": [asdict(c) for c in battery.cases],
        },
        "questions": per_question,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2))

    t = totals.as_dict()
    print("## Execution-grounded battery (mock provider)")
    print(f"questions: {t['n_questions']}")
    print(f"execution success rate: {t['execution_success_rate']:.1%}")
    print(f"null-result rate: {t['null_result_rate']:.1%}")
    print(f"execution errors: {t['execution_errors'] or 'none'}")
    print(f"equivalence: {t['equivalence']}")
    print(f"governance: {t['governance']}")
    print(f"questions with full scan: {t['questions_with_full_scan']}")
    for budget, r in t["retrieval_per_budget"].items():
        fk = f"{r['fk_recall']:.1%}" if r["fk_recall"] is not None else "n/a"
        print(
            f"retrieval {budget}: recall={r['recall']:.1%} "
            f"precision={r['precision']:.1%} full-recall={r['full_recall']:.1%} "
            f"fk-recall={fk} (n={r['fk_questions']}) latency={r['latency_ms']:.1f}ms"
        )
    rmd = asdict(rm)
    print(
        f"repair (synthetic fixture): success={rmd['repair_success_rate']:.1%} "
        f"mean_attempts={rmd['mean_attempts']:.2f} "
        f"escalation={rmd['escalation_rate']:.1%} unhandled={rmd['unhandled_rate']:.1%}"
    )
    print(f"adversarial battery: {battery.passed}/{battery.total} passed")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
