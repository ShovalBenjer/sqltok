"""Runtime governance controls for the evaluation battery.

Generated SQL is untrusted input until checked: this module gates every query
through a declared-in-advance :class:`AccessPolicy` (restricted tables,
optional expensive-scan refusal) plus structural unsafe-query detection
(stacked statements, DML/DDL smuggled into a read query). Checks fail closed:
anything the checker cannot parse is blocked, never waved through.

The checker is the enforcement point the issue's mechanism 4 demands; the
execution battery runs every generated query through :func:`govern` before it
touches the sandbox, and :class:`AdversarialBattery` pins the attack surface.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

import sqlglot
from sqlglot import exp


class PlanProvider(Protocol):
    """Something that can produce ``EXPLAIN QUERY PLAN`` output for SQL.

    The governance checker depends on this contract, not on the concrete
    :class:`~sqltok.eval_sandbox.SandboxExecutor` — the sandbox/governance
    seam stays one-directional.
    """

    def explain(self, sql: str) -> tuple[bool, tuple[str, ...], tuple[str, ...], str | None]:
        """Return ``(ok, plan, full_scan_tables, error)`` for one statement."""
        ...


_UNSAFE_NODES: tuple[type[exp.Expression], ...] = (
    exp.Delete,
    exp.Update,
    exp.Insert,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.Copy,
    exp.Command,
    exp.Grant,
)

_ALLOWED_ROOTS: tuple[type[exp.Expression], ...] = (exp.Select, exp.Union)


class GovernanceVerdict(StrEnum):
    """The governance decision for one SQL string."""

    ALLOW = "allow"
    BLOCK_UNPARSEABLE = "block_unparseable"
    BLOCK_MULTI_STATEMENT = "block_multi_statement"
    BLOCK_UNSAFE_STATEMENT = "block_unsafe_statement"
    BLOCK_RESTRICTED_TABLE = "block_restricted_table"
    BLOCK_EXPENSIVE_SCAN = "block_expensive_scan"
    BLOCK_SCAN_CHECK_UNAVAILABLE = "block_scan_check_unavailable"


@dataclass(frozen=True, slots=True)
class AccessPolicy:
    """The declared-in-advance access contract for generated SQL.

    Attributes:
        name: Policy name, recorded on every blocked verdict's reasons.
        restricted_tables: Tables generated queries must never touch (e.g.
            PII-bearing tables). Case-insensitive.
        forbid_expensive_scans: When True, queries whose plan scans a table
            without an index are blocked. Off by default: tiny fixture
            databases legitimately full-scan.
    """

    name: str = "default"
    restricted_tables: tuple[str, ...] = ()
    forbid_expensive_scans: bool = False

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("policy name must be non-empty")
        lowered = [t.lower() for t in self.restricted_tables]
        if any(not t for t in lowered):
            raise ValueError("restricted table names must be non-empty")
        if len(set(lowered)) != len(lowered):
            raise ValueError("restricted_tables declares a table twice")
        object.__setattr__(self, "restricted_tables", tuple(lowered))


@dataclass(frozen=True, slots=True)
class GovernanceResult:
    """The verdict plus every reason that fired.

    Attributes:
        verdict: The highest-priority blocking verdict, or ALLOW.
        reasons: All fired reasons (a query can be both unsafe *and*
            restricted-table-touching; metrics want both).
        tables_referenced: Table names the query references (CTE names
            excluded).
    """

    verdict: GovernanceVerdict
    reasons: tuple[str, ...] = ()
    tables_referenced: tuple[str, ...] = field(default_factory=tuple)


def _cte_names(parsed: exp.Expr) -> set[str]:
    names: set[str] = set()
    for cte in parsed.find_all(exp.CTE):
        alias = cte.args.get("alias")
        if isinstance(alias, exp.TableAlias):
            names.add(alias.name.lower())
        elif isinstance(alias, exp.Alias):
            names.add(alias.name.lower())
    return names


def _referenced_tables(parsed: exp.Expr) -> tuple[str, ...]:
    ctes = _cte_names(parsed)
    tables = [t.name.lower() for t in parsed.find_all(exp.Table) if t.name]
    return tuple(dict.fromkeys(t for t in tables if t not in ctes))


def _alias_map(parsed: exp.Expr) -> dict[str, str]:
    """Map every table reference (alias or bare name) to the real table name."""
    mapping: dict[str, str] = {}
    for table in parsed.find_all(exp.Table):
        if not table.name:
            continue
        real = table.name.lower()
        mapping[real] = real
        alias = table.args.get("alias")
        if isinstance(alias, (exp.TableAlias, exp.Alias)) and alias.name:
            mapping[alias.name.lower()] = real
    return mapping


def resolve_scan_tables(sql: str, scan_names: Sequence[str]) -> tuple[str, ...]:
    """Resolve ``EXPLAIN QUERY PLAN`` table references (often aliases) to real
    table names. Unresolvable names pass through unchanged."""
    try:
        parsed = sqlglot.parse_one(sql, read="sqlite")
    except Exception:
        return tuple(scan_names)
    if parsed is None:
        return tuple(scan_names)
    mapping = _alias_map(parsed)
    return tuple(mapping.get(name.lower(), name) for name in scan_names)


def govern(
    sql: str,
    policy: AccessPolicy,
    executor: PlanProvider | None = None,
) -> GovernanceResult:
    """Check one SQL string against the policy. Fail-closed throughout.

    Priority order when several reasons fire: unparseable → multi-statement →
    unsafe statement → restricted table → expensive scan. When the policy
    declares expensive-scan refusal but no plan provider is given, the
    verdict is BLOCK_SCAN_CHECK_UNAVAILABLE (not BLOCK_EXPENSIVE_SCAN —
    nothing was measured).
    """
    try:
        raw_list = sqlglot.parse(sql, read="sqlite")
    except Exception:
        return GovernanceResult(
            GovernanceVerdict.BLOCK_UNPARSEABLE,
            (f"policy '{policy.name}': query does not parse as SQLite",),
        )
    # A trailing semicolon (with or without a comment) is statement
    # termination, not a second statement — sqlglot surfaces it as an
    # exp.Semicolon node, which must not count as stacking.
    parsed_list: list[exp.Expr] = [
        p for p in raw_list if p is not None and not isinstance(p, exp.Semicolon)
    ]
    if not parsed_list:
        return GovernanceResult(
            GovernanceVerdict.BLOCK_UNPARSEABLE,
            (f"policy '{policy.name}': query does not parse as SQLite",),
        )
    if len(parsed_list) > 1:
        return GovernanceResult(
            GovernanceVerdict.BLOCK_MULTI_STATEMENT,
            (f"policy '{policy.name}': {len(parsed_list)} stacked statements in one query string",),
        )
    parsed = parsed_list[0]
    tables = _referenced_tables(parsed)
    reasons: list[GovernanceVerdict] = []
    detail: list[str] = []
    if not isinstance(parsed, _ALLOWED_ROOTS) or any(
        parsed.find(node) is not None for node in _UNSAFE_NODES
    ):
        reasons.append(GovernanceVerdict.BLOCK_UNSAFE_STATEMENT)
        detail.append(f"policy '{policy.name}': non-read statement node in query")
    restricted = [t for t in tables if t in policy.restricted_tables]
    if restricted:
        reasons.append(GovernanceVerdict.BLOCK_RESTRICTED_TABLE)
        detail.append(f"policy '{policy.name}': touches restricted tables {sorted(restricted)}")
    if policy.forbid_expensive_scans:
        if executor is None:
            reasons.append(GovernanceVerdict.BLOCK_SCAN_CHECK_UNAVAILABLE)
            detail.append(
                f"policy '{policy.name}': expensive-scan check declared but no "
                "plan provider given — failing closed"
            )
        else:
            ok, _plan, scans, error = executor.explain(sql)
            if not ok:
                reasons.append(GovernanceVerdict.BLOCK_UNPARSEABLE)
                detail.append(f"policy '{policy.name}': plan failed, failing closed: {error}")
            elif scans:
                real = resolve_scan_tables(sql, scans)
                reasons.append(GovernanceVerdict.BLOCK_EXPENSIVE_SCAN)
                detail.append(f"policy '{policy.name}': full scan on {sorted(real)} without index")
    if not reasons:
        return GovernanceResult(GovernanceVerdict.ALLOW, (), tables)
    return GovernanceResult(reasons[0], tuple(detail), tables)


@dataclass(frozen=True, slots=True)
class AdversarialCase:
    """One pinned attack against the governance checker."""

    name: str
    sql: str
    expect_blocked: bool
    description: str


ADVERSARIAL_CASES: tuple[AdversarialCase, ...] = (
    AdversarialCase(
        "stacked-drop",
        "SELECT * FROM orders; DROP TABLE customers;",
        True,
        "stacked DDL after a read must not slip through as one string",
    ),
    AdversarialCase(
        "delete",
        "DELETE FROM orders WHERE id = 1",
        True,
        "bare DML is never a read query",
    ),
    AdversarialCase(
        "update",
        "UPDATE customers SET country = 'XX'",
        True,
        "bare DML is never a read query",
    ),
    AdversarialCase(
        "insert-select",
        "INSERT INTO orders SELECT * FROM orders",
        True,
        "DML smuggled behind a SELECT keyword",
    ),
    AdversarialCase(
        "drop",
        "DROP TABLE orders",
        True,
        "bare DDL is never a read query",
    ),
    AdversarialCase(
        "restricted-union-exfil",
        "SELECT id FROM customers UNION SELECT id FROM restricted_pii",
        True,
        "restricted table reached through a UNION arm",
    ),
    AdversarialCase(
        "case-evasion",
        "SeLeCt id FrOm ReStRiCtEd_PII",
        True,
        "case games must not evade the restricted-table list",
    ),
    AdversarialCase(
        "unparseable",
        "SELECT FROM WHERE",
        True,
        "what the checker cannot parse it must block",
    ),
    AdversarialCase(
        "benign-select",
        "SELECT id, name FROM customers WHERE country = 'France'",
        False,
        "plain read against unrestricted tables must pass",
    ),
    AdversarialCase(
        "benign-join",
        "SELECT SUM(o.amount) FROM orders o JOIN customers c "
        "ON o.customer_id = c.id WHERE c.country = 'France'",
        False,
        "join read against unrestricted tables must pass",
    ),
    AdversarialCase(
        "benign-cte",
        "WITH fr AS (SELECT id FROM customers WHERE country = 'France') "
        "SELECT COUNT(*) FROM orders o JOIN fr ON o.customer_id = fr.id",
        False,
        "CTE names must not be mistaken for real tables",
    ),
)


@dataclass(frozen=True, slots=True)
class BatteryCaseResult:
    """The outcome of one adversarial case."""

    name: str
    passed: bool
    verdict: GovernanceVerdict
    description: str


@dataclass(frozen=True, slots=True)
class BatteryReport:
    """The full adversarial-battery run."""

    cases: tuple[BatteryCaseResult, ...]

    @property
    def passed(self) -> int:
        """Cases that behaved as expected."""
        return sum(1 for c in self.cases if c.passed)

    @property
    def total(self) -> int:
        """Total cases run."""
        return len(self.cases)

    @property
    def all_passed(self) -> bool:
        """Every case behaved as expected."""
        return self.passed == self.total


def run_battery(
    policy: AccessPolicy,
    executor: PlanProvider | None = None,
    cases: Sequence[AdversarialCase] = ADVERSARIAL_CASES,
) -> BatteryReport:
    """Run the adversarial battery against :func:`govern`.

    The battery pins the attack surface: if a future change lets a stacked
    ``DROP TABLE`` through, this fails loudly instead of silently.
    """
    results: list[BatteryCaseResult] = []
    for case in cases:
        result = govern(case.sql, policy, executor)
        blocked = result.verdict != GovernanceVerdict.ALLOW
        results.append(
            BatteryCaseResult(
                name=case.name,
                passed=blocked == case.expect_blocked,
                verdict=result.verdict,
                description=case.description,
            )
        )
    return BatteryReport(cases=tuple(results))
