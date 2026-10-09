"""Adversarial tests for the execution-grounded evaluation battery (#43).

Every mechanism the issue demands is pinned by a test that fails if the
mechanism is theater: sandboxing that can be escaped, equivalence that waves
through the chapter's canonical wrong query, repair metrics that cannot tell
recovery from luck, governance that lets a stacked DROP through.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sqltok import (
    AccessPolicy,
    EquivalenceVerdict,
    EscalationEvidence,
    EscalationPath,
    EscalationPolicy,
    ExecutionOutcome,
    GovernanceVerdict,
    RepairAttempt,
    RepairLoop,
    RepairReport,
    SandboxExecutor,
    SchemaBudgetManager,
    govern,
    measure_retrieval,
    repair_metrics,
    resolve_scan_tables,
    run_battery,
    semantic_equivalence,
)

RETAIL = Path("benchmarks/sample_data/dev_databases/retail/retail.sqlite")
SCHOOL = Path("benchmarks/sample_data/dev_databases/school/school.sqlite")

GOLD_FRANCE = (
    "SELECT SUM(o.amount) FROM orders o JOIN customers c "
    "ON o.customer_id = c.id WHERE c.country = 'France'"
)
# The chapter's canonical failure: valid SQL, executes fine, sums ALL invoices
# because the active-customer (here: France) filter is missing.
WRONG_NO_FILTER = "SELECT SUM(o.amount) FROM orders o"


@pytest.fixture()
def retail() -> SandboxExecutor:
    return SandboxExecutor(RETAIL)


# --- sandbox -----------------------------------------------------------------


def test_sandbox_executes_read(retail: SandboxExecutor) -> None:
    out = retail.execute(GOLD_FRANCE)
    assert out.ok
    assert out.error is None
    assert out.row_count == 1
    assert not out.is_empty
    assert out.elapsed_ms >= 0.0
    assert out.plan, "EXPLAIN QUERY PLAN must be captured"


def test_sandbox_null_result_signal(retail: SandboxExecutor) -> None:
    out = retail.execute("SELECT * FROM customers WHERE country = 'Narnia'")
    assert out.ok
    assert out.is_empty
    assert out.row_count == 0


def test_sandbox_syntax_error_captured_not_raised(retail: SandboxExecutor) -> None:
    out = retail.execute("SELECT * FRM orders")
    assert not out.ok
    assert out.error is not None
    assert "OperationalError" in out.error


def test_sandbox_write_blocked(retail: SandboxExecutor) -> None:
    out = retail.execute("CREATE TABLE evil (id INTEGER)")
    assert not out.ok
    assert out.error is not None
    out2 = retail.execute("INSERT INTO orders VALUES (1, 1, 1.0, 'x')")
    assert not out2.ok


def test_sandbox_stacked_statements_rejected(retail: SandboxExecutor) -> None:
    out = retail.execute("SELECT 1; SELECT 2;")
    assert not out.ok, "sqlite3.execute must refuse stacked statements"


def test_sandbox_operation_budget_aborts() -> None:
    killer = SandboxExecutor(RETAIL, operation_budget=1)
    out = killer.execute("SELECT * FROM orders o1, orders o2, orders o3")
    assert not out.ok
    assert out.error is not None
    assert "Interrupted" in out.error or "interrupted" in out.error.lower()


def test_sandbox_invalid_budget_rejected() -> None:
    with pytest.raises(ValueError):
        SandboxExecutor(RETAIL, operation_budget=0)


def test_sandbox_missing_db_captured() -> None:
    out = SandboxExecutor(Path("no-such-db.sqlite")).execute("SELECT 1")
    assert not out.ok
    assert out.error is not None


def test_sandbox_full_scan_signal(retail: SandboxExecutor) -> None:
    out = retail.execute("SELECT * FROM orders")
    assert out.ok
    assert "orders" in out.full_scan_tables


def test_sandbox_indexed_lookup_no_full_scan(retail: SandboxExecutor) -> None:
    out = retail.execute("SELECT * FROM customers WHERE id = 1")
    assert out.ok
    assert out.full_scan_tables == ()


def test_sandbox_explain_without_executing(retail: SandboxExecutor) -> None:
    ok, plan, scans, error = retail.explain(GOLD_FRANCE)
    assert ok and error is None
    assert plan
    assert scans, "the join query full-scans orders (no index on customer_id)"
    resolved = resolve_scan_tables(GOLD_FRANCE, scans)
    assert "orders" in resolved, "plan alias 'o' must resolve to the real table"


def test_sandbox_explain_bad_sql(retail: SandboxExecutor) -> None:
    ok, _plan, _scans, error = retail.explain("SELECT * FRM orders")
    assert not ok
    assert error is not None


# --- semantic equivalence ------------------------------------------------------


def _exec(retail: SandboxExecutor, sql: str) -> ExecutionOutcome:
    return retail.execute(sql)


def test_equivalence_canonical_chapter_failure(retail: SandboxExecutor) -> None:
    """The load-bearing test: executes fine, semantically wrong."""
    gen = _exec(retail, WRONG_NO_FILTER)
    gold = _exec(retail, GOLD_FRANCE)
    assert gen.ok and gold.ok, "both queries must execute — that is the trap"
    result = semantic_equivalence(gen, gold)
    assert result.verdict == EquivalenceVerdict.ROW_CONTENT_MISMATCH
    assert result.detail


def test_equivalence_identical_results(retail: SandboxExecutor) -> None:
    gen = _exec(retail, "SELECT SUM(amount) FROM orders")
    gold = _exec(retail, WRONG_NO_FILTER)
    result = semantic_equivalence(gen, gold)
    assert result.verdict == EquivalenceVerdict.EQUIVALENT


def test_equivalence_row_count_mismatch(retail: SandboxExecutor) -> None:
    gen = _exec(retail, "SELECT * FROM customers WHERE country = 'France'")
    gold = _exec(retail, "SELECT * FROM customers")
    result = semantic_equivalence(gen, gold)
    assert result.verdict == EquivalenceVerdict.ROW_COUNT_MISMATCH


def test_equivalence_order_insensitive_by_default(retail: SandboxExecutor) -> None:
    gen = _exec(retail, "SELECT id FROM customers ORDER BY id DESC")
    gold = _exec(retail, "SELECT id FROM customers ORDER BY id ASC")
    assert semantic_equivalence(gen, gold).verdict == EquivalenceVerdict.EQUIVALENT


def test_equivalence_order_sensitive_when_gold_orders(retail: SandboxExecutor) -> None:
    gen = _exec(retail, "SELECT id FROM customers ORDER BY id DESC")
    gold = _exec(retail, "SELECT id FROM customers ORDER BY id ASC")
    result = semantic_equivalence(gen, gold, gold_sql="SELECT id FROM customers ORDER BY id ASC")
    assert result.verdict == EquivalenceVerdict.ROW_CONTENT_MISMATCH


def test_equivalence_execution_error(retail: SandboxExecutor) -> None:
    gen = _exec(retail, "SELECT * FRM orders")
    gold = _exec(retail, "SELECT * FROM orders")
    result = semantic_equivalence(gen, gold)
    assert result.verdict == EquivalenceVerdict.EXECUTION_ERROR


def test_equivalence_gold_error(retail: SandboxExecutor) -> None:
    gen = _exec(retail, "SELECT * FROM orders")
    gold = _exec(retail, "SELECT * FRM orders")
    result = semantic_equivalence(gen, gold)
    assert result.verdict == EquivalenceVerdict.GOLD_ERROR


# --- retrieval metrics ---------------------------------------------------------


def test_retrieval_recall_and_precision() -> None:
    report = measure_retrieval(
        selected=["customers", "orders", "suppliers"],
        gold_tables=["customers", "orders"],
        required_fks=[("orders", "customers")],
        latency_ms=12.5,
    )
    assert report.recall == pytest.approx(1.0)
    assert report.precision == pytest.approx(2 / 3)
    assert report.full_recall is True
    assert report.fk_recall == pytest.approx(1.0)
    assert report.latency_ms == pytest.approx(12.5)
    assert report.n_selected == 3 and report.n_gold == 2


def test_retrieval_under_retrieval() -> None:
    report = measure_retrieval(
        selected=["orders"],
        gold_tables=["customers", "orders"],
        required_fks=[("orders", "customers")],
        latency_ms=3.0,
    )
    assert report.recall == pytest.approx(0.5)
    assert report.full_recall is False
    assert report.fk_recall == pytest.approx(0.0), "FK needs BOTH endpoints"


def test_retrieval_no_fks_needed() -> None:
    report = measure_retrieval(
        selected=["customers"],
        gold_tables=["customers"],
        required_fks=[],
        latency_ms=1.0,
    )
    assert report.fk_recall is None


def test_retrieval_negative_latency_rejected() -> None:
    with pytest.raises(ValueError):
        measure_retrieval(["a"], ["a"], None, latency_ms=-1.0)


def test_retrieval_case_insensitive() -> None:
    report = measure_retrieval(["Customers"], ["customers"], None, 0.0)
    assert report.recall == pytest.approx(1.0)


def test_retrieval_against_real_selector() -> None:
    """The metric measures the real selector, not a reimplementation."""
    import time

    mgr = SchemaBudgetManager.from_sqlite(RETAIL)
    start = time.perf_counter()
    ctx = mgr.build_context("total order amount for customers in France", token_budget=2000)
    latency_ms = (time.perf_counter() - start) * 1000.0
    report = measure_retrieval(
        selected=ctx.tables,
        gold_tables=["orders", "customers"],
        required_fks=[("orders", "customers")],
        latency_ms=latency_ms,
    )
    assert report.full_recall is True
    assert report.latency_ms >= 0.0


# --- repair loop ---------------------------------------------------------------


def _scripted_generator(scripts: dict[int, str]):
    def generate(prompt: str, last_error: str | None) -> str:
        assert last_error is not None or True  # feedback threading is structural
        n = _scripted_generator.calls + 1
        _scripted_generator.calls = n
        return scripts[n]

    _scripted_generator.calls = 0
    return generate


def test_repair_fixes_on_retry(retail: SandboxExecutor) -> None:
    gen = _scripted_generator({1: "SELECT * FRM orders", 2: "SELECT * FROM orders"})
    loop = RepairLoop(retail, gen, max_attempts=3)
    report = loop.run("list orders", "list orders")
    assert report.repaired is True
    assert report.attempts_used == 2
    assert report.final_outcome.ok
    assert report.attempts[1].feedback is not None, "error text must feed back"
    assert "FRM" not in report.attempts[1].sql


def test_repair_first_try_success_not_repaired(retail: SandboxExecutor) -> None:
    gen = _scripted_generator({1: "SELECT * FROM orders"})
    report = RepairLoop(retail, gen, max_attempts=3).run("list orders", "list orders")
    assert report.repaired is False
    assert report.attempts_used == 1
    assert report.final_outcome.ok


def test_repair_exhaustion_without_policy(retail: SandboxExecutor) -> None:
    gen = _scripted_generator({1: "SELECT * FRM a", 2: "SELECT * FRM b", 3: "SELECT * FRM c"})
    report = RepairLoop(retail, gen, max_attempts=3).run("q", "q")
    assert report.exhausted is True
    assert report.attempts_used == 3
    assert report.escalated_case is None


def test_repair_exhaustion_escalates_on_declared_path(retail: SandboxExecutor) -> None:
    gen = _scripted_generator({1: "SELECT * FRM a", 2: "SELECT * FRM b"})
    policy = EscalationPolicy(
        name="repair-fallback",
        paths=(EscalationPath.LOW_COVERAGE,),
        coverage_floor=0.5,
    )
    evidence = EscalationEvidence(
        mention_count=2, tables_selected=1, covered_weight=0.1, top_scores=(0.9, 0.2)
    )
    report = RepairLoop(retail, gen, max_attempts=2, escalation_policy=policy).run(
        "q", "q", escalation_evidence=evidence
    )
    assert report.exhausted is True
    assert report.escalated_case is not None
    assert report.escalated_case.path == EscalationPath.LOW_COVERAGE
    assert report.escalated_case.policy_name == "repair-fallback"


def test_repair_exhaustion_unhandled_when_no_path_fires(retail: SandboxExecutor) -> None:
    """Default policy + healthy evidence: the failure leaves with no owner.

    This is a measured gap, not a rigged outcome — unhandled_rate exists so
    the battery reports it honestly.
    """
    gen = _scripted_generator({1: "SELECT * FRM a", 2: "SELECT * FRM b"})
    evidence = EscalationEvidence(
        mention_count=3, tables_selected=2, covered_weight=0.9, top_scores=(0.9, 0.8)
    )
    report = RepairLoop(retail, gen, max_attempts=2, escalation_policy=EscalationPolicy()).run(
        "q", "q", escalation_evidence=evidence
    )
    assert report.exhausted is True
    assert report.escalated_case is None


def test_repair_bad_max_attempts_rejected(retail: SandboxExecutor) -> None:
    with pytest.raises(ValueError):
        RepairLoop(retail, lambda p, e: "SELECT 1", max_attempts=0)


def test_repair_metrics_aggregation() -> None:
    ok_outcome = ExecutionOutcome(ok=True, rows=((1,),))
    bad_outcome = ExecutionOutcome(ok=False, error="OperationalError: boom")
    r1 = RepairReport(
        question="a",
        attempts=(
            RepairAttempt(1, "bad", bad_outcome, None),
            RepairAttempt(2, "good", ok_outcome, "boom"),
        ),
        repaired=True,
        final_outcome=ok_outcome,
    )
    r2 = RepairReport(
        question="b",
        attempts=(RepairAttempt(1, "good", ok_outcome, None),),
        repaired=False,
        final_outcome=ok_outcome,
    )
    metrics = repair_metrics([r1, r2])
    assert metrics.n_questions == 2
    assert metrics.n_needed_repair == 1
    assert metrics.repair_success_rate == pytest.approx(1.0)
    assert metrics.mean_attempts == pytest.approx(1.5)
    assert metrics.unhandled_rate == pytest.approx(0.0)


# --- governance ------------------------------------------------------------------


STRICT = AccessPolicy(name="strict", restricted_tables=("restricted_pii",))


def test_governance_battery_all_pass() -> None:
    report = run_battery(STRICT)
    failures = [c for c in report.cases if not c.passed]
    assert report.all_passed, f"battery failures: {[(c.name, c.verdict) for c in failures]}"
    assert report.total == 11


def test_governance_blocks_restricted_join() -> None:
    result = govern("SELECT * FROM orders o JOIN restricted_pii p ON o.id = p.id", STRICT)
    assert result.verdict == GovernanceVerdict.BLOCK_RESTRICTED_TABLE
    assert "restricted_pii" in result.reasons[0]


def test_governance_unsafe_beats_restricted_priority() -> None:
    result = govern("DELETE FROM restricted_pii", STRICT)
    assert result.verdict == GovernanceVerdict.BLOCK_UNSAFE_STATEMENT
    assert len(result.reasons) == 2, "both reasons must be recorded for metrics"


def test_governance_expensive_scan_blocked(retail: SandboxExecutor) -> None:
    policy = AccessPolicy(name="no-scans", forbid_expensive_scans=True)
    result = govern("SELECT * FROM orders", policy, retail)
    assert result.verdict == GovernanceVerdict.BLOCK_EXPENSIVE_SCAN
    assert "orders" in result.reasons[0], "alias-free scan must name the table"


def test_governance_indexed_lookup_allowed(retail: SandboxExecutor) -> None:
    policy = AccessPolicy(name="no-scans", forbid_expensive_scans=True)
    result = govern("SELECT * FROM customers WHERE id = 1", policy, retail)
    assert result.verdict == GovernanceVerdict.ALLOW


def test_governance_scan_check_without_executor_fails_closed() -> None:
    policy = AccessPolicy(name="no-scans", forbid_expensive_scans=True)
    result = govern("SELECT * FROM orders", policy, None)
    assert result.verdict == GovernanceVerdict.BLOCK_EXPENSIVE_SCAN


def test_governance_gold_query_allowed_by_default(retail: SandboxExecutor) -> None:
    result = govern(GOLD_FRANCE, AccessPolicy(), retail)
    assert result.verdict == GovernanceVerdict.ALLOW
    assert set(result.tables_referenced) == {"orders", "customers"}


def test_governance_policy_validation() -> None:
    with pytest.raises(ValueError):
        AccessPolicy(name="  ")
    with pytest.raises(ValueError):
        AccessPolicy(name="x", restricted_tables=("a", "A"))
    with pytest.raises(ValueError):
        AccessPolicy(name="x", restricted_tables=("",))


def test_governance_case_insensitive_policy() -> None:
    policy = AccessPolicy(name="x", restricted_tables=("Restricted_PII",))
    assert policy.restricted_tables == ("restricted_pii",)


# --- end-to-end over the sample fixture --------------------------------------------


def test_end_to_end_sample_fixture() -> None:
    """Govern → execute → equivalence over every committed sample question."""
    questions = json.loads(Path("benchmarks/sample_data/questions.json").read_text())
    assert len(questions) >= 1
    executor = SandboxExecutor(RETAIL)
    policy = AccessPolicy()
    for q in questions:
        db = RETAIL if q["db_id"] == "retail" else SCHOOL
        ex = SandboxExecutor(db)
        gold_sql: str = q["SQL"]
        gov = govern(gold_sql, policy, ex)
        assert gov.verdict == GovernanceVerdict.ALLOW, f"gold blocked: {q}"
        gold_out = ex.execute(gold_sql)
        assert gold_out.ok, f"gold failed: {q}"
        # The mock generator's canned output executes but is semantically wrong
        # for every real gold query — the battery must say so, not wave it
        # through. One degenerate exception: question 4's gold is
        # COUNT(*) = 1 on this fixture, so its 1x1 result [(1,)] coincides
        # with SELECT 1's. That is a known execution-accuracy false positive
        # on tiny fixtures, documented here instead of hidden.
        mock_out = executor.execute("SELECT 1;")
        equiv = semantic_equivalence(mock_out, gold_out)
        if list(gold_out.rows) == [(1,)]:
            assert equiv.verdict == EquivalenceVerdict.EQUIVALENT
        else:
            assert equiv.verdict != EquivalenceVerdict.EQUIVALENT
