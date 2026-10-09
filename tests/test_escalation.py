"""Adversarial tests for the escalation protocol (issue #38).

Escalation is a planned branch of the protocol, not a failure. These tests
attack the four acceptance criteria at theory level:

1. Paths declared in advance — an undeclared path can never fire, and the
   policy rejects malformed declarations.
2. Escalated cases excluded from automated scores — even when an escalated
   case carries a score, it cannot leak into the statistics.
3. Escalation is normal operation in metrics — reported as routing telemetry,
   with no failure accounting anywhere in the types.
4. The state/record invariant is wired, not prose — mismatched state and
   record raise instead of silently drifting.
"""

from __future__ import annotations

import pytest

from sqltok import (
    DecisionState,
    EscalatedCase,
    EscalationEvidence,
    EscalationPath,
    EscalationPolicy,
    EscalationReport,
    SchemaBudgetManager,
    SchemaContext,
    ScoredDecision,
    summarize,
)
from sqltok.context import SchemaContext as DirectContext


def _evidence(
    *,
    mention_count: int = 2,
    tables_selected: int = 2,
    covered_weight: float | None = 0.8,
    top_scores: tuple[float, ...] = (0.9, 0.4),
) -> EscalationEvidence:
    return EscalationEvidence(
        mention_count=mention_count,
        tables_selected=tables_selected,
        covered_weight=covered_weight,
        top_scores=top_scores,
    )


# -- 1. paths are declared in advance -----------------------------------------


def test_undeclared_path_never_fires() -> None:
    """A policy declaring only BUDGET_EXHAUSTED ignores all other triggers."""
    policy = EscalationPolicy(name="narrow", paths=(EscalationPath.BUDGET_EXHAUSTED,))
    # Evidence that would fire NO_GROUNDING, LOW_COVERAGE and AMBIGUOUS_GROUNDING
    # under the default policy — none of them are declared here.
    hostile = _evidence(
        mention_count=0, covered_weight=0.0, top_scores=(0.7, 0.7), tables_selected=3
    )
    assert policy.evaluate("q", hostile) is None


def test_declaration_order_is_priority() -> None:
    """When several triggers fire, the first *declared* path wins."""
    evidence = _evidence(mention_count=0, tables_selected=0)  # fires both
    first_wins = EscalationPolicy(
        paths=(EscalationPath.BUDGET_EXHAUSTED, EscalationPath.NO_GROUNDING)
    )
    assert first_wins.evaluate("q", evidence).path is EscalationPath.BUDGET_EXHAUSTED  # type: ignore[union-attr]
    reversed_policy = EscalationPolicy(
        paths=(EscalationPath.NO_GROUNDING, EscalationPath.BUDGET_EXHAUSTED)
    )
    assert reversed_policy.evaluate("q", evidence).path is EscalationPath.NO_GROUNDING  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"paths": ()},
        {"paths": (EscalationPath.LOW_COVERAGE, EscalationPath.LOW_COVERAGE)},
        {"coverage_floor": -0.1},
        {"coverage_floor": 1.1},
        {"ambiguity_epsilon": -1e-9},
        {"ambiguity_top_k": 1},
        {"arbiter": "   "},
    ],
)
def test_policy_rejects_malformed_declarations(kwargs: object) -> None:
    """Malformed declarations raise at construction, not at decision time."""
    with pytest.raises(ValueError):
        EscalationPolicy(**kwargs)  # type: ignore[arg-type]


def test_policy_rejects_string_paths() -> None:
    """Plain strings are not declarations: only EscalationPath members pass."""
    with pytest.raises(ValueError):
        EscalationPolicy(paths=("no_grounding",))  # type: ignore[arg-type]


def test_unknown_coverage_never_trips_low_coverage() -> None:
    """LOW_COVERAGE needs a reported coverage; unknown coverage is not zero."""
    policy = EscalationPolicy(paths=(EscalationPath.LOW_COVERAGE,))
    assert policy.evaluate("q", _evidence(covered_weight=None)) is None


def test_unknown_mentions_never_trip_no_grounding() -> None:
    """mention_count=-1 (unknown) is not 'no grounding'."""
    policy = EscalationPolicy(paths=(EscalationPath.NO_GROUNDING,))
    assert policy.evaluate("q", _evidence(mention_count=-1)) is None


# -- 2. escalated cases are excluded from automated scores --------------------


def test_escalated_scores_cannot_leak_into_statistics() -> None:
    """Even an escalated case carrying a score is excluded from the stats."""
    decisions = [
        ScoredDecision(DecisionState.SERVED, None, 1.0),
        ScoredDecision(DecisionState.SERVED, None, 0.0),
        ScoredDecision(DecisionState.SERVED, None, None),  # served but unscored
        # Adversarial: someone attached a perfect score to an escalated case.
        ScoredDecision(DecisionState.ESCALATED, EscalationPath.NO_GROUNDING, 1.0),
        ScoredDecision(DecisionState.ESCALATED, EscalationPath.LOW_COVERAGE, None),
    ]
    report = summarize(decisions)
    assert report.served == 3
    assert report.escalated == 2
    assert report.scored_served == 2
    assert report.mean_score_served == pytest.approx(0.5)  # (1.0+0.0)/2, leak-proof
    assert report.per_path == {
        EscalationPath.NO_GROUNDING: 1,
        EscalationPath.LOW_COVERAGE: 1,
    }
    assert report.escalation_rate == pytest.approx(2 / 5)


def test_summarize_empty_is_total() -> None:
    report = summarize([])
    assert report.total == 0
    assert report.escalation_rate == 0.0
    assert report.mean_score_served is None


def test_scored_decision_rejects_mismatched_pairs() -> None:
    """ESCALATED needs a path, SERVED must not name one — wired, not hygiene."""
    with pytest.raises(ValueError):
        ScoredDecision(DecisionState.ESCALATED, None, 0.5)
    with pytest.raises(ValueError):
        ScoredDecision(DecisionState.SERVED, EscalationPath.NO_GROUNDING, 0.5)
    ok = ScoredDecision(DecisionState.ESCALATED, EscalationPath.NO_GROUNDING, 0.5)
    assert ok.path is EscalationPath.NO_GROUNDING


# -- 3. escalation is normal operation, never a failure -----------------------


def test_decision_state_space_has_no_failure() -> None:
    """The closed state space cannot express 'escalation as failure'."""
    assert set(DecisionState) == {DecisionState.SERVED, DecisionState.ESCALATED}


def test_report_carries_no_failure_accounting() -> None:
    """No failure field, no failure language in the rendered report."""
    report = EscalationReport(
        served=8,
        escalated=2,
        per_path={EscalationPath.NO_GROUNDING: 2},
        scored_served=8,
        mean_score_served=0.75,
    )
    assert not any("fail" in f for f in EscalationReport.__dataclass_fields__)
    rendered = report.render().lower()
    # The only failure-adjacent language is the explicit denial.
    assert rendered.count("failure") == 1
    assert "not a failure" in rendered
    assert "normal" in rendered


# -- 4. the state/record invariant is wired -----------------------------------


def _case() -> EscalatedCase:
    return EscalatedCase(
        question="q",
        path=EscalationPath.BUDGET_EXHAUSTED,
        arbiter="human",
        policy_name="p",
        evidence={"tables_selected": 0},
    )


def test_record_without_state_raises() -> None:
    with pytest.raises(ValueError):
        DirectContext(
            text="t",
            tables=[],
            token_count=1,
            budget=10,
            encoding_name="e",
            escalation=_case(),  # state left at default SERVED
        )


def test_state_without_record_raises() -> None:
    with pytest.raises(ValueError):
        DirectContext(
            text="t",
            tables=[],
            token_count=1,
            budget=10,
            encoding_name="e",
            decision_state=DecisionState.ESCALATED,  # no record attached
        )


def test_consistent_pair_is_accepted() -> None:
    ctx = DirectContext(
        text="t",
        tables=[],
        token_count=1,
        budget=10,
        encoding_name="e",
        decision_state=DecisionState.ESCALATED,
        escalation=_case(),
    )
    assert ctx.decision_state is DecisionState.ESCALATED


# -- 5. manager integration: the protocol branch is real ----------------------


def test_no_policy_preserves_legacy_behavior(sample_ddl: str) -> None:
    """Without a policy the manager behaves exactly as before: always SERVED."""
    mgr = SchemaBudgetManager.from_ddl(sample_ddl)
    ctx = mgr.build_context("total order amount by customer region")
    assert ctx.decision_state is DecisionState.SERVED
    assert ctx.escalation is None
    assert ctx.grounded_mentions >= 0  # coverage selector reports grounding
    assert ctx.coverage_reported is True


def test_budget_exhausted_escalates_through_manager(sample_ddl: str) -> None:
    """A budget that fits nothing escalates; it is not a silent empty context."""
    mgr = SchemaBudgetManager.from_ddl(sample_ddl)
    policy = EscalationPolicy(name="strict-budget")
    ctx = mgr.build_context("total order amount", token_budget=1, escalation_policy=policy)
    assert ctx.tables == []
    assert ctx.decision_state is DecisionState.ESCALATED
    assert ctx.escalation is not None
    assert ctx.escalation.path is EscalationPath.BUDGET_EXHAUSTED
    assert ctx.escalation.arbiter == "human"
    assert ctx.escalation.policy_name == "strict-budget"


def test_no_grounding_escalates_through_manager(sample_ddl: str) -> None:
    """A question with no schema-affine phrases escalates instead of blind packing."""
    mgr = SchemaBudgetManager.from_ddl(sample_ddl)
    policy = EscalationPolicy(name="grounded-only")
    ctx = mgr.build_context("tell me about xyzzy plugh", escalation_policy=policy)
    assert ctx.grounded_mentions == 0
    assert ctx.decision_state is DecisionState.ESCALATED
    assert ctx.escalation is not None
    assert ctx.escalation.path is EscalationPath.NO_GROUNDING
    assert ctx.escalation.evidence == {"mention_count": 0}


def test_low_coverage_path_is_independent(sample_ddl: str) -> None:
    """LOW_COVERAGE fires on its own declaration even when grounding succeeded."""
    mgr = SchemaBudgetManager.from_ddl(sample_ddl)
    policy = EscalationPolicy(
        name="picky", paths=(EscalationPath.LOW_COVERAGE,), coverage_floor=0.999
    )
    ctx = mgr.build_context("total order amount by customer region", escalation_policy=policy)
    assert ctx.grounded_mentions > 0  # grounding did succeed
    assert ctx.decision_state is DecisionState.ESCALATED
    assert ctx.escalation is not None
    assert ctx.escalation.path is EscalationPath.LOW_COVERAGE


def test_ambiguous_tie_escalates() -> None:
    """A tie at the top within epsilon is contender ambiguity, not a decision."""
    policy = EscalationPolicy(paths=(EscalationPath.AMBIGUOUS_GROUNDING,), ambiguity_epsilon=1e-6)
    tied = _evidence(top_scores=(0.8, 0.8, 0.1))
    case = policy.evaluate("q", tied)
    assert case is not None
    assert case.path is EscalationPath.AMBIGUOUS_GROUNDING
    assert case.evidence["top_score"] == pytest.approx(0.8)

    clear_winner = _evidence(top_scores=(0.8, 0.5, 0.1))
    assert policy.evaluate("q", clear_winner) is None

    single_contender = _evidence(top_scores=(0.8,))
    assert policy.evaluate("q", single_contender) is None


def test_served_question_passes_default_policy(sample_ddl: str) -> None:
    """A well-grounded question under a lenient floor is served, not escalated."""
    mgr = SchemaBudgetManager.from_ddl(sample_ddl)
    policy = EscalationPolicy(name="lenient", coverage_floor=0.0)
    ctx = mgr.build_context("total order amount by customer region", escalation_policy=policy)
    assert ctx.decision_state is DecisionState.SERVED
    assert ctx.escalation is None
    assert len(ctx.tables) > 0


def test_escalated_context_still_respects_budget(sample_ddl: str) -> None:
    """Escalation never smuggles an over-budget context past the ceiling."""
    mgr = SchemaBudgetManager.from_ddl(sample_ddl)
    policy = EscalationPolicy(name="default")
    ctx = mgr.build_context(
        "total order amount by customer region",
        token_budget=50,
        escalation_policy=policy,
    )
    assert ctx.token_count <= 50


def test_inert_policy_on_non_grounding_selector(sample_ddl: str) -> None:
    """Unknown evidence never escalates: a non-grounding selector's policy is inert.

    The greedy selector reports no grounding (mention_count=-1, coverage None,
    no scores), so NO_GROUNDING / LOW_COVERAGE / AMBIGUOUS_GROUNDING cannot
    fire — unknown is not zero. The protocol serves; escalation_rate stays 0.
    """
    from sqltok import RelevanceGreedySelector, parse_ddl

    schema = parse_ddl(sample_ddl)
    mgr = SchemaBudgetManager(schema, selector=RelevanceGreedySelector(schema))
    ctx = mgr.build_context(
        "total order amount by customer region",
        escalation_policy=EscalationPolicy(name="greedy"),
    )
    assert ctx.decision_state is DecisionState.SERVED
    assert ctx.escalation is None
    assert ctx.grounded_mentions == -1
    assert ctx.coverage_reported is False


def test_schema_context_is_still_a_context(sample_ddl: str) -> None:
    """The public type did not change shape: escalation fields are additive."""
    ctx = SchemaContext(text="t", tables=["a"], token_count=1, budget=10, encoding_name="e")
    assert ctx.decision_state is DecisionState.SERVED
    assert ctx.escalation is None
