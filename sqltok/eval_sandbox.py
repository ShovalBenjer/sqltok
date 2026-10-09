"""Sandboxed, read-only SQL execution for evaluation.

Every generated query in the execution-grounded battery runs through
:class:`SandboxExecutor`: the database is opened read-only, a VM-operation
budget aborts runaway queries, and failures are *captured* as data
(:class:`ExecutionOutcome`) rather than raised — a query that errors is a
measurement, not a crash.
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

#: Matches a bare ``SCAN <table>`` plan step with no index usage.
_SCAN_RE = re.compile(r"^SCAN\s+(\S+?)(?:\s|$)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    """What happened when one SQL string met the sandbox.

    Attributes:
        ok: The query executed without error.
        rows: Result rows as tuples (empty when ``ok`` is False).
        row_count: ``len(rows)``.
        is_empty: The query ran fine but returned zero rows (the null-result
            signal from the evaluation chapter).
        error: ``"<ExceptionClass>: <message>"`` when ``ok`` is False, else
            ``None``.
        error_class: The exception class name alone (``None`` when ``ok``),
            for typed consumers that count failures by class without parsing
            the message string.
        elapsed_ms: Wall-clock execution time in milliseconds.
        plan: ``EXPLAIN QUERY PLAN`` detail strings (empty when ``ok`` is
            False).
        full_scan_tables: Tables the plan scans without an index. First-class
            efficiency signal, not an afterthought. Plan pseudo-steps
            (``SCAN CONSTANT ROW``, ``SCAN (subquery-N)``) are excluded;
            table aliases keep the plan's own spelling — use
            :func:`sqltok.resolve_scan_tables` to map them to real tables.
    """

    ok: bool
    rows: tuple[tuple[object, ...], ...] = ()
    error: str | None = None
    error_class: str | None = None
    elapsed_ms: float = 0.0
    plan: tuple[str, ...] = ()
    full_scan_tables: tuple[str, ...] = field(default_factory=tuple)

    @property
    def row_count(self) -> int:
        """Number of result rows."""
        return len(self.rows)

    @property
    def is_empty(self) -> bool:
        """The query executed successfully but returned no rows."""
        return self.ok and not self.rows


class SandboxExecutor:
    """Execute SQL against a SQLite file under read-only, budgeted sandboxing.

    Args:
        db_path: Path to the SQLite database file.
        operation_budget: Maximum SQLite VM operations per statement before
            the run is aborted (fail-closed timeout). ``None`` disables the
            budget.

    The connection opens the file with ``mode=ro`` *and* sets
    ``PRAGMA query_only = ON``: writes fail even if the URI mode is somehow
    bypassed. :meth:`execute` never raises for query failures — it returns
    an :class:`ExecutionOutcome` with ``ok=False``.
    """

    def __init__(self, db_path: Path, operation_budget: int | None = 10_000_000) -> None:
        self._db_path = db_path
        if operation_budget is not None and operation_budget < 1:
            raise ValueError("operation_budget must be positive or None")
        self._operation_budget = operation_budget

    def _connect(self) -> sqlite3.Connection:
        uri = f"file:{self._db_path.resolve()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.execute("PRAGMA query_only = ON")
        if self._operation_budget is not None:
            budget = self._operation_budget

            def _abort() -> int:
                return 1  # nonzero aborts the running statement

            conn.set_progress_handler(_abort, budget)
        return conn

    @staticmethod
    def _full_scans(plan: tuple[str, ...]) -> tuple[str, ...]:
        found: list[str] = []
        for detail in plan:
            if "USING" in detail.upper():
                continue
            match = _SCAN_RE.match(detail.strip())
            if not match:
                continue
            name = match.group(1)
            # Plan pseudo-steps name no table: SCAN CONSTANT ROW (a query over
            # no tables at all) and SCAN (subquery-N). Aliases keep the plan's
            # own spelling — sqltok.resolve_scan_tables maps them to real
            # tables for human-facing messages.
            if name.upper() == "CONSTANT" or name.startswith("("):
                continue
            if name not in found:
                found.append(name)
        return tuple(found)

    def explain(self, sql: str) -> tuple[bool, tuple[str, ...], tuple[str, ...], str | None]:
        """Return ``(ok, plan, full_scan_tables, error)`` for one statement.

        Runs only ``EXPLAIN QUERY PLAN`` — the query itself is never executed.
        """
        try:
            conn = self._connect()
        except Exception as exc:  # fail-closed by contract
            return False, (), (), f"{type(exc).__name__}: {exc}"
        try:
            try:
                plan_rows = conn.execute(f"EXPLAIN QUERY PLAN {sql}").fetchall()
            except Exception as exc:  # fail-closed by contract
                return False, (), (), f"{type(exc).__name__}: {exc}"
            plan = tuple(str(row[3]) for row in plan_rows)
            return True, plan, self._full_scans(plan), None
        finally:
            conn.close()

    def execute(self, sql: str) -> ExecutionOutcome:
        """Run one SQL statement in the sandbox and capture the outcome."""
        try:
            conn = self._connect()
        except Exception as exc:  # fail-closed by contract
            return ExecutionOutcome(
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
                error_class=type(exc).__name__,
            )
        try:
            start = time.perf_counter()
            try:
                cursor = conn.execute(sql)
                rows = tuple(tuple(row) for row in cursor.fetchall())
                elapsed_ms = (time.perf_counter() - start) * 1000.0
            except Exception as exc:  # fail-closed by contract
                elapsed_ms = (time.perf_counter() - start) * 1000.0
                return ExecutionOutcome(
                    ok=False,
                    error=f"{type(exc).__name__}: {exc}",
                    error_class=type(exc).__name__,
                    elapsed_ms=elapsed_ms,
                )
            try:
                plan_rows = conn.execute(f"EXPLAIN QUERY PLAN {sql}").fetchall()
                plan = tuple(str(row[3]) for row in plan_rows)
            except sqlite3.Error:
                plan = ()
            return ExecutionOutcome(
                ok=True,
                rows=rows,
                elapsed_ms=elapsed_ms,
                plan=plan,
                full_scan_tables=self._full_scans(plan),
            )
        finally:
            conn.close()
