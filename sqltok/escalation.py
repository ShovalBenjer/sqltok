"""Escalation as a planned branch of the protocol (issue #38).

Escalation-to-human is a designed branch of the selection protocol, not a
failure mode. This module declares the protocol's outcome states, the
escalation paths that are recognised *in advance*, and the metric discipline
that keeps escalated cases out of automated scores.

The acceptance contract from the issue, wired as code rather than prose:

- Escalation paths are declared in advance: :class:`EscalationPolicy` names the
  live :class:`EscalationPath` members up front, and
  :meth:`EscalationPolicy.evaluate` can only fire a declared path. An
  undeclared path never escalates, whatever the evidence.
- Escalated cases are excluded from automated scores: :func:`summarize`
  computes score statistics over ``SERVED`` decisions only, by construction.
- Escalation is normal operation in metrics: :class:`EscalationReport`
  publishes the escalation rate and per-path counts as routing telemetry.
- Counting escalation as failure is not representable: :class:`DecisionState`
  is a closed two-member enum — there is no failure member, and the report
  carries no failure accounting.

The module is dependency-free (stdlib only) so the protocol can be reasoned
about and tested without the retrieval stack.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum


class DecisionState(StrEnum):
    """First-class outcome states of the context-building protocol.

    The state space is closed on purpose: a context is either ``SERVED`` by the
    automated protocol or ``ESCALATED`` to the declared arbiter. There is
    deliberately no ``FAILED`` member — escalation is normal operation, never
    a failure, so "escalation as failure" cannot be expressed in this type.
    """

    SERVED = "served"
    ESCALATED = "escalated"


class EscalationPath(StrEnum):
    """Escalation paths, declared in advance by the policy.

    Each member names one trigger condition the protocol recognises *before*
    selection runs. A case escalates only along a path the active
    :class:`EscalationPolicy` declared; the declaration order is the priority
    order when several triggers fire at once.
    """

    NO_GROUNDING = "no_grounding"
    BUDGET_EXHAUSTED = "budget_exhausted"
    LOW_COVERAGE = "low_coverage"
    AMBIGUOUS_GROUNDING = "ambiguous_grounding"


_PATH_DESCRIPTIONS: dict[EscalationPath, str] = {
    EscalationPath.NO_GROUNDING: (
        "grounding produced no mentions: the selector ran blind and an arbiter "
        "should confirm the question is answerable from this schema"
    ),
    EscalationPath.BUDGET_EXHAUSTED: (
        "no table fits the token budget: the selection is empty and an arbiter "
        "should decide whether the budget or the question is wrong"
    ),
    EscalationPath.LOW_COVERAGE: (
        "grounded mention coverage fell below the declared floor: the context "
        "is unlikely to support the question and an arbiter should review it"
    ),
    EscalationPath.AMBIGUOUS_GROUNDING: (
        "the top grounding contenders are tied within the declared epsilon: "
        "an arbiter should break the tie rather than the protocol guessing"
    ),
}


@dataclass(frozen=True, slots=True)
class EscalationEvidence:
    """The observable facts one escalation decision is made from.

    Attributes:
        mention_count: Grounded mentions for the question (``0`` means the
            selector ran blind). ``-1`` marks "unknown" for selectors that do
            not ground at all; the ``NO_GROUNDING`` path does not fire on
            unknown evidence.
        tables_selected: Tables in the built context.
        covered_weight: Fraction of grounded mention weight covered, or
            ``None`` when the selector does not report coverage. The
            ``LOW_COVERAGE`` path does not fire on ``None``.
        top_scores: Ranked per-table grounding scores, best first. The
            ``AMBIGUOUS_GROUNDING`` path needs at least two positive scores.
    """

    mention_count: int
    tables_selected: int
    covered_weight: float | None
    top_scores: tuple[float, ...] = ()


@dataclass(frozen=True, slots=True)
class EscalatedCase:
    """The record of one escalation: what, along which declared path, to whom.

    Attributes:
        question: The question that escalated.
        path: The declared :class:`EscalationPath` that fired.
        arbiter: Who the case escalates to (declared by the policy, e.g.
            ``"human"``).
        policy_name: Name of the policy whose declaration admitted this path.
        evidence: The per-path evidence snapshot behind the decision.
    """

    question: str
    path: EscalationPath
    arbiter: str
    policy_name: str
    evidence: dict[str, float | int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EscalationPolicy:
    """The declared-in-advance escalation contract for the protocol.

    Attributes:
        name: Policy name, recorded on every :class:`EscalatedCase`.
        paths: The live escalation paths, in priority order. Only these paths
            can fire; anything else in the evidence is ignored.
        coverage_floor: ``LOW_COVERAGE`` fires when reported coverage is
            strictly below this (``0.0``–``1.0``).
        ambiguity_epsilon: ``AMBIGUOUS_GROUNDING`` fires when the gap between
            the best and second-best grounding score is at most this.
        ambiguity_top_k: Only the top-k scores participate in the tie check.
        arbiter: Who escalated cases go to.
    """

    name: str = "default"
    paths: tuple[EscalationPath, ...] = (
        EscalationPath.NO_GROUNDING,
        EscalationPath.BUDGET_EXHAUSTED,
        EscalationPath.LOW_COVERAGE,
        EscalationPath.AMBIGUOUS_GROUNDING,
    )
    coverage_floor: float = 0.25
    ambiguity_epsilon: float = 1e-6
    ambiguity_top_k: int = 3
    arbiter: str = "human"

    def __post_init__(self) -> None:
        if not self.paths:
            raise ValueError("escalation policy must declare at least one path")
        if len(set(self.paths)) != len(self.paths):
            raise ValueError("escalation policy declares a path twice")
        if not all(isinstance(p, EscalationPath) for p in self.paths):
            raise ValueError("paths must be EscalationPath members, not plain strings")
        if not 0.0 <= self.coverage_floor <= 1.0:
            raise ValueError("coverage_floor must lie in [0.0, 1.0]")
        if self.ambiguity_epsilon < 0.0:
            raise ValueError("ambiguity_epsilon must be non-negative")
        if self.ambiguity_top_k < 2:
            raise ValueError("ambiguity_top_k must be at least 2")
        if not self.arbiter.strip():
            raise ValueError("arbiter must be a non-empty descriptor")

    def describe(self, path: EscalationPath) -> str:
        """Plain-language account of what a path means (for arbiter routing)."""
        return _PATH_DESCRIPTIONS[path]

    def evaluate(self, question: str, evidence: EscalationEvidence) -> EscalatedCase | None:
        """Decide the protocol branch for one question.

        Returns an :class:`EscalatedCase` for the first declared path whose
        trigger fires (declaration order is priority order), or ``None`` when
        no declared path fires — i.e. the protocol serves the context itself.
        """
        for path in self.paths:
            if _triggered(path, evidence, self):
                return EscalatedCase(
                    question=question,
                    path=path,
                    arbiter=self.arbiter,
                    policy_name=self.name,
                    evidence=_evidence_snapshot(path, evidence),
                )
        return None


def _triggered(
    path: EscalationPath, evidence: EscalationEvidence, policy: EscalationPolicy
) -> bool:
    """Whether one declared path's trigger condition holds on the evidence."""
    if path == EscalationPath.NO_GROUNDING:
        return evidence.mention_count == 0
    if path == EscalationPath.BUDGET_EXHAUSTED:
        return evidence.tables_selected == 0
    if path == EscalationPath.LOW_COVERAGE:
        return (
            evidence.covered_weight is not None and evidence.covered_weight < policy.coverage_floor
        )
    if path == EscalationPath.AMBIGUOUS_GROUNDING:
        scores = evidence.top_scores[: policy.ambiguity_top_k]
        return (
            len(scores) >= 2
            and scores[0] > 0.0
            and (scores[0] - scores[1]) <= policy.ambiguity_epsilon
        )
    raise AssertionError(f"unhandled escalation path: {path}")  # pragma: no cover


def _evidence_snapshot(
    path: EscalationPath, evidence: EscalationEvidence
) -> dict[str, float | int]:
    """The per-path evidence recorded on the escalated case."""
    if path is EscalationPath.NO_GROUNDING:
        return {"mention_count": evidence.mention_count}
    if path is EscalationPath.BUDGET_EXHAUSTED:
        return {"tables_selected": evidence.tables_selected}
    if path is EscalationPath.LOW_COVERAGE:
        return {"covered_weight": evidence.covered_weight or 0.0}
    if path is EscalationPath.AMBIGUOUS_GROUNDING:
        top = evidence.top_scores[:2]
        return {"top_score": top[0], "second_score": top[1]}
    raise AssertionError(f"unhandled escalation path: {path}")  # pragma: no cover


@dataclass(frozen=True, slots=True)
class ScoredDecision:
    """One protocol outcome paired with its automated score, if any.

    ``score`` is ``None`` for unscored decisions. An escalated decision may
    still carry a score (e.g. a late human grade); :func:`summarize` excludes
    it from automated statistics regardless.
    """

    state: DecisionState
    path: EscalationPath | None
    score: float | None

    def __post_init__(self) -> None:
        if (self.path is not None) != (self.state == DecisionState.ESCALATED):
            raise ValueError(
                "ScoredDecision consistency: an ESCALATED decision must name "
                "its path, and a SERVED decision must not"
            )


@dataclass(frozen=True, slots=True)
class EscalationReport:
    """Aggregate protocol outcomes with escalation as normal operation.

    Score statistics cover ``SERVED`` decisions only — escalated cases are
    excluded from automated scores by construction. Escalation appears as
    routing telemetry (rate + per-path counts), never as a failure ledger:
    there is deliberately no failure field on this type.
    """

    served: int
    escalated: int
    per_path: dict[EscalationPath, int]
    scored_served: int
    mean_score_served: float | None

    @property
    def total(self) -> int:
        """Decisions aggregated (served + escalated)."""
        return self.served + self.escalated

    @property
    def escalation_rate(self) -> float:
        """Share of decisions routed to the arbiter; ``0.0`` when empty."""
        if not self.total:
            return 0.0
        return self.escalated / self.total

    def render(self) -> str:
        """Human-readable summary; escalation is reported as normal routing."""
        lines = [
            f"decisions: {self.total} "
            f"(served={self.served}, escalated={self.escalated}, "
            f"escalation_rate={self.escalation_rate:.3f})",
            "escalation is a normal protocol branch, not a failure: "
            "escalated cases are routed to the arbiter and excluded from "
            "automated scores.",
        ]
        for path in EscalationPath:
            count = self.per_path.get(path, 0)
            if count:
                lines.append(f"  {path.value}: {count}")
        if self.mean_score_served is None:
            lines.append("automated score over served cases: unscored")
        else:
            lines.append(
                f"automated score over served cases: "
                f"mean={self.mean_score_served:.3f} (n={self.scored_served})"
            )
        return "\n".join(lines)


def summarize(decisions: Iterable[ScoredDecision]) -> EscalationReport:
    """Aggregate protocol outcomes into an :class:`EscalationReport`.

    The exclusion discipline is structural: score statistics accumulate over
    ``SERVED`` decisions only, so an escalated case can never leak into an
    automated score — not even when it carries a ``score`` value.
    """
    served = 0
    escalated = 0
    per_path: dict[EscalationPath, int] = {}
    score_total = 0.0
    scored_served = 0
    for decision in decisions:
        if decision.state == DecisionState.ESCALATED:
            escalated += 1
            if decision.path is not None:
                per_path[decision.path] = per_path.get(decision.path, 0) + 1
        else:
            served += 1
            if decision.score is not None:
                score_total += decision.score
                scored_served += 1
    return EscalationReport(
        served=served,
        escalated=escalated,
        per_path=per_path,
        scored_served=scored_served,
        mean_score_served=(score_total / scored_served) if scored_served else None,
    )
