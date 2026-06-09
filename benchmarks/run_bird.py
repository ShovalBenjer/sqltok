#!/usr/bin/env python3
"""BIRD mini-dev benchmark harness for SQLTok.

Runs two arms with the *same* model and *same* prompt template, differing only in
schema context:

* ``baseline`` -- the full schema dump (all CREATE TABLE statements + 1 sample
  row per table).
* ``sqltok`` -- :class:`sqltok.SchemaBudgetManager` output at one or more token
  budgets.

Predicted SQL is written in BIRD's prediction format so the *official* execution
-accuracy script (see ``benchmarks/third_party/bird_eval/``) can score it. Raw
LLM responses are cached to disk so reruns are free and resumable.

Example (free, no API keys, on the committed sample fixture)::

    python benchmarks/run_bird.py --provider mock --data-dir benchmarks/sample_data --limit 5

Example (real run on BIRD mini-dev)::

    python benchmarks/run_bird.py --provider anthropic --model claude-3-5-sonnet \\
        --data-dir benchmarks/data --budgets 1000 2000 4000
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Make the in-repo package importable when run from a source checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm import DiskCache, build_client  # noqa: E402

from sqltok import SchemaBudgetManager  # noqa: E402
from sqltok.tokenizer import TokenCounter  # noqa: E402

SYSTEM_PROMPT = (
    "You are an expert SQLite analyst. Given a database schema and a question, "
    "write ONE valid SQLite query that answers it. Return only the SQL, with no "
    "explanation and no markdown fences."
)

PROMPT_TEMPLATE = """Database schema:
{schema}

{evidence}Question: {question}

SQLite query:"""


@dataclass
class QuestionRecord:
    """One BIRD-style question."""

    question_id: int
    db_id: str
    question: str
    evidence: str = ""
    gold_sql: str = ""


@dataclass
class ArmResult:
    """Accumulated per-arm metrics."""

    arm: str
    schema_tokens: list[int] = field(default_factory=list)
    input_tokens: list[int] = field(default_factory=list)
    output_tokens: list[int] = field(default_factory=list)
    cost: float = 0.0
    predictions: dict[str, str] = field(default_factory=dict)
    rows: list[dict] = field(default_factory=list)


def load_questions(path: Path) -> list[QuestionRecord]:
    """Load a BIRD-format questions JSON file."""
    raw = json.loads(path.read_text())
    records = []
    for i, item in enumerate(raw):
        records.append(
            QuestionRecord(
                question_id=item.get("question_id", i),
                db_id=item["db_id"],
                question=item["question"],
                evidence=item.get("evidence", "") or "",
                gold_sql=item.get("SQL", item.get("query", "")) or "",
            )
        )
    return records


def db_path_for(db_root: Path, db_id: str) -> Path:
    """Resolve the SQLite file for a database id (BIRD layout or flat)."""
    candidates = [
        db_root / db_id / f"{db_id}.sqlite",
        db_root / f"{db_id}.sqlite",
        db_root / db_id / f"{db_id}.db",
    ]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(f"No SQLite file found for db_id={db_id!r} under {db_root}")


def clean_sql(text: str) -> str:
    """Strip markdown fences/labels and collapse to a single-line SQL string."""
    text = text.strip()
    if text.startswith("```"):
        lines = [ln for ln in text.splitlines() if not ln.strip().startswith("```")]
        text = "\n".join(lines)
        if text.lower().startswith("sql"):
            text = text[3:]
    return " ".join(text.split()).strip().rstrip(";") + ";"


def build_arms(budgets: list[int], run_baseline: bool) -> list[str]:
    arms = []
    if run_baseline:
        arms.append("baseline")
    arms.extend(f"sqltok@{b}" for b in budgets)
    return arms


def schema_context_for(
    arm: str, mgr: SchemaBudgetManager, question: str, counter: TokenCounter
) -> tuple[str, int]:
    """Return (schema_text, schema_token_count) for an arm."""
    if arm == "baseline":
        text = mgr.full_schema_text(include_sample_rows=True)
        return text, counter.count(text)
    budget = int(arm.split("@", 1)[1])
    ctx = mgr.build_context(question, token_budget=budget)
    return ctx.text, ctx.token_count


def percentile(values: list[int], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def run(args: argparse.Namespace) -> None:
    data_dir = Path(args.data_dir)
    questions_path = Path(args.questions) if args.questions else data_dir / "questions.json"
    db_root = Path(args.db_root) if args.db_root else data_dir / "dev_databases"
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    counter = TokenCounter(args.encoding)
    cache = DiskCache(Path(args.cache_dir))
    client = build_client(args.provider, args.model, cache=cache)
    if args.in_price is not None:
        type(client).input_price_per_m = args.in_price
    if args.out_price is not None:
        type(client).output_price_per_m = args.out_price

    questions = load_questions(questions_path)
    if args.limit:
        questions = questions[: args.limit]

    arms = build_arms(args.budgets, run_baseline=not args.no_baseline)
    results = {arm: ArmResult(arm=arm) for arm in arms}

    managers: dict[str, SchemaBudgetManager] = {}

    for q in questions:
        if q.db_id not in managers:
            managers[q.db_id] = SchemaBudgetManager.from_sqlite(
                db_path_for(db_root, q.db_id), sample_rows=args.sample_rows
            )
        mgr = managers[q.db_id]
        evidence = f"Hint: {q.evidence}\n\n" if q.evidence else ""

        for arm in arms:
            schema_text, schema_tokens = schema_context_for(arm, mgr, q.question, counter)
            prompt = PROMPT_TEMPLATE.format(
                schema=schema_text, evidence=evidence, question=q.question
            )
            response = client.complete(SYSTEM_PROMPT, prompt)
            sql = clean_sql(response.text)

            res = results[arm]
            res.schema_tokens.append(schema_tokens)
            res.input_tokens.append(response.input_tokens)
            res.output_tokens.append(response.output_tokens)
            res.cost += client.cost(response.input_tokens, response.output_tokens)
            # BIRD prediction format: "SQL\t----- bird -----\tdb_id"
            res.predictions[str(q.question_id)] = f"{sql}\t----- bird -----\t{q.db_id}"
            res.rows.append(
                {
                    "question_id": q.question_id,
                    "db_id": q.db_id,
                    "arm": arm,
                    "schema_tokens": schema_tokens,
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                    "predicted_sql": sql,
                    "gold_sql": q.gold_sql,
                    "cached": response.cached,
                }
            )
        print(f"[{q.question_id}] {q.db_id}: done ({len(arms)} arms)", file=sys.stderr)

    write_outputs(results, out_dir, args)
    print(f"\nWrote results to {out_dir/'results.md'}", file=sys.stderr)


def write_outputs(results: dict[str, ArmResult], out_dir: Path, args: argparse.Namespace) -> None:
    # Per-question JSONL.
    jsonl_path = out_dir / "per_question.jsonl"
    with jsonl_path.open("w") as fh:
        for res in results.values():
            for row in res.rows:
                fh.write(json.dumps(row) + "\n")

    # BIRD-format predictions per arm (for the official eval script).
    for arm, res in results.items():
        safe = arm.replace("@", "_").replace("/", "_")
        (out_dir / f"predict_{safe}.json").write_text(json.dumps(res.predictions, indent=2))

    # Markdown summary table.
    lines = [
        "# SQLTok BIRD mini-dev results",
        "",
        f"- model: `{args.model}`  provider: `{args.provider}`",
        f"- questions: {len(next(iter(results.values())).rows) if results else 0}",
        f"- encoding: `{args.encoding}`",
        "",
        "| arm | schema tok (mean) | schema tok (p95) | total input tok | "
        "exec acc | est. cost (USD) |",
        "|-----|------:|------:|------:|------:|------:|",
    ]
    for arm, res in results.items():
        mean_schema = statistics.mean(res.schema_tokens) if res.schema_tokens else 0
        p95_schema = percentile(res.schema_tokens, 0.95)
        total_input = sum(res.input_tokens)
        acc = "n/a (run eval)" if args.provider == "mock" else "pending"
        lines.append(
            f"| {arm} | {mean_schema:.0f} | {p95_schema:.0f} | {total_input} | "
            f"{acc} | {res.cost:.4f} |"
        )
    lines += [
        "",
        "Execution accuracy is computed by BIRD's official script; see "
        "`benchmarks/third_party/bird_eval/README.md`. Run it against the "
        "`predict_*.json` files in this directory and paste the numbers into the "
        "`exec acc` column.",
        "",
    ]
    (out_dir / "results.md").write_text("\n".join(lines))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run the SQLTok BIRD mini-dev benchmark.")
    p.add_argument("--provider", default="mock", choices=["mock", "anthropic", "openai"])
    p.add_argument("--model", default="mock-1", help="Model name for the chosen provider.")
    p.add_argument("--data-dir", default="benchmarks/data")
    p.add_argument("--questions", default=None, help="Override questions JSON path.")
    p.add_argument("--db-root", default=None, help="Override database root directory.")
    p.add_argument("--out-dir", default="benchmarks/results")
    p.add_argument("--cache-dir", default="benchmarks/.llm_cache")
    p.add_argument(
        "--budgets", type=int, nargs="+", default=[1000, 2000, 4000],
        help="Token budgets for the sqltok arm.",
    )
    p.add_argument("--no-baseline", action="store_true", help="Skip the full-dump arm.")
    p.add_argument("--limit", type=int, default=0, help="Only run the first N questions.")
    p.add_argument("--sample-rows", type=int, default=3)
    p.add_argument("--encoding", default="cl100k_base")
    p.add_argument("--in-price", type=float, default=None, help="USD per 1M input tokens.")
    p.add_argument("--out-price", type=float, default=None, help="USD per 1M output tokens.")
    return p.parse_args(argv)


if __name__ == "__main__":
    run(parse_args())
