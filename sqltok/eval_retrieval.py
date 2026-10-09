"""Retrieval recall AND precision for the evaluation battery.

The issue's under/over-retrieval distinction: under-retrieval (missing required
tables) causes schema hallucination and invalid joins; over-retrieval
(irrelevant schema objects in context) costs tokens and confuses planning.
This module measures both sides plus foreign-key coverage and the retrieval
latency the issue demands — as a pure function over an already-run retrieval,
so the benchmark measures the real selector, not a reimplementation.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetrievalReport:
    """One retrieval measurement.

    Attributes:
        recall: Fraction of gold tables present in the selection.
        precision: Fraction of selected tables that are gold tables.
        full_recall: Every gold table was selected (the ceiling on achievable
            execution accuracy for the question).
        latency_ms: Wall-clock time the retrieval took.
        fk_recall: Fraction of required foreign-key edges whose *both*
            endpoint tables were selected; ``None`` when the question needs
            no foreign keys.
        n_selected: Number of tables selected.
        n_gold: Number of gold tables.
    """

    recall: float
    precision: float
    full_recall: bool
    latency_ms: float
    fk_recall: float | None
    n_selected: int
    n_gold: int


def measure_retrieval(
    selected: Collection[str],
    gold_tables: Collection[str],
    required_fks: Collection[tuple[str, str]] | None,
    latency_ms: float,
) -> RetrievalReport:
    """Compute recall/precision/FK-coverage for one retrieval.

    Args:
        selected: Table names the selector put in context.
        gold_tables: Table names the reference SQL touches.
        required_fks: ``(table_a, table_b)`` pairs the reference query's joins
            need; ``None``/empty means the question needs no joins.
        latency_ms: Measured retrieval latency (timed by the caller around
            the real selector call).
    """
    sel = {t.lower() for t in selected}
    gold = {t.lower() for t in gold_tables}
    hits = sel & gold
    recall = len(hits) / len(gold) if gold else 1.0
    precision = len(hits) / len(sel) if sel else (1.0 if not gold else 0.0)
    fk_recall: float | None = None
    if required_fks:
        pairs = [(a.lower(), b.lower()) for a, b in required_fks]
        covered = sum(1 for a, b in pairs if a in sel and b in sel)
        fk_recall = covered / len(pairs)
    if latency_ms < 0:
        raise ValueError("latency_ms must be non-negative")
    return RetrievalReport(
        recall=recall,
        precision=precision,
        full_recall=gold <= sel,
        latency_ms=latency_ms,
        fk_recall=fk_recall,
        n_selected=len(sel),
        n_gold=len(gold),
    )
