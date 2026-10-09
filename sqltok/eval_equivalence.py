"""Semantic-equivalence checking for the execution-grounded battery.

Syntax-valid SQL is not semantically-correct SQL: a generated query can
execute successfully yet be wrong (the chapter's canonical example — the user
asks for revenue from *active* customers, the system sums *all* invoices
without the active-customer filter). This module compares what the generated
query *returned* against what the trusted reference query returned, on the
same sandbox database.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum

import sqlglot
from sqlglot import exp

from .eval_sandbox import ExecutionOutcome


class EquivalenceVerdict(StrEnum):
    """The outcome of one generated-vs-reference comparison."""

    EQUIVALENT = "equivalent"
    ROW_COUNT_MISMATCH = "row_count_mismatch"
    ROW_CONTENT_MISMATCH = "row_content_mismatch"
    EXECUTION_ERROR = "execution_error"
    GOLD_ERROR = "gold_error"


@dataclass(frozen=True, slots=True)
class EquivalenceResult:
    """The verdict plus a human-readable account of the difference."""

    verdict: EquivalenceVerdict
    detail: str


def _has_order_by(sql: str) -> bool:
    # Structural check, not a substring search: a string literal containing
    # the words "order by" must not flip the comparison into ordered mode.
    if not sql.strip():
        return False
    try:
        parsed = sqlglot.parse_one(sql, read="sqlite")
    except Exception:
        return False
    return parsed is not None and parsed.find(exp.Order) is not None


def semantic_equivalence(
    generated: ExecutionOutcome,
    gold: ExecutionOutcome,
    gold_sql: str,
) -> EquivalenceResult:
    """Compare a generated query's result against the reference query's.

    Row comparison is order-insensitive (multiset) unless the gold SQL carries
    an ``ORDER BY``, in which case sequence order is part of the contract.
    ``gold_sql`` is required (not defaulted): silently defaulting to
    order-insensitive comparison would weaken the check without the caller
    noticing. ``NULL`` compares equal to ``NULL``; values compare by Python
    equality (so ``1 == 1.0`` — value equality, not type equality; no
    tolerance theater, just the language's own ``==``).
    """
    if not gold.ok:
        return EquivalenceResult(
            EquivalenceVerdict.GOLD_ERROR,
            f"reference query failed: {gold.error}",
        )
    if not generated.ok:
        return EquivalenceResult(
            EquivalenceVerdict.EXECUTION_ERROR,
            f"generated query failed: {generated.error}",
        )
    if generated.row_count != gold.row_count:
        return EquivalenceResult(
            EquivalenceVerdict.ROW_COUNT_MISMATCH,
            f"generated returned {generated.row_count} rows, reference returned {gold.row_count}",
        )
    if _has_order_by(gold_sql):
        if list(generated.rows) != list(gold.rows):
            return EquivalenceResult(
                EquivalenceVerdict.ROW_CONTENT_MISMATCH,
                "ordered rows differ from the reference",
            )
    elif Counter(generated.rows) != Counter(gold.rows):
        return EquivalenceResult(
            EquivalenceVerdict.ROW_CONTENT_MISMATCH,
            "row multisets differ from the reference",
        )
    return EquivalenceResult(EquivalenceVerdict.EQUIVALENT, "results match")
