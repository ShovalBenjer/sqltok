"""Query-repair loop and repair-pipeline metrics.

The battery treats repair as a measurable pipeline stage, not prose: generate
→ sandbox-execute → on failure feed the *error text* back as feedback → retry
(up to ``max_attempts``). When repair is exhausted, the declared
:class:`~sqltok.escalation.EscalationPolicy` is evaluated and the resulting
case (or its absence — an unhandled failure, itself a measured signal) is
recorded. Metrics are pure functions over the recorded reports.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .escalation import EscalatedCase, EscalationEvidence, EscalationPolicy
from .eval_sandbox import ExecutionOutcome, SandboxExecutor

#: Signature of the SQL generator under repair: (prompt, last_error) -> sql.
#: ``last_error`` is None on the first attempt and the previous attempt's
#: error text afterwards.
GeneratorFn = Callable[[str, str | None], str]


@dataclass(frozen=True, slots=True)
class RepairAttempt:
    """One attempt inside a repair loop."""

    attempt_no: int
    sql: str
    outcome: ExecutionOutcome
    feedback: str | None


@dataclass(frozen=True, slots=True)
class RepairReport:
    """The full record of one question's repair trajectory.

    Attributes:
        question: The natural-language question.
        attempts: Every attempt, in order.
        repaired: The first attempt failed and a later one succeeded.
        final_outcome: The last attempt's outcome.
        escalated_case: The case the escalation policy produced on exhaustion,
            or ``None`` when no policy was given or no declared path fired.
        exhausted: Repair ran out of attempts without success.
    """

    question: str
    attempts: tuple[RepairAttempt, ...]
    repaired: bool
    final_outcome: ExecutionOutcome
    escalated_case: EscalatedCase | None = None
    exhausted: bool = False

    @property
    def attempts_used(self) -> int:
        """Number of attempts consumed."""
        return len(self.attempts)


@dataclass(frozen=True, slots=True)
class RepairMetrics:
    """Aggregate repair-pipeline metrics over many questions."""

    n_questions: int
    n_needed_repair: int
    repair_success_rate: float
    mean_attempts: float
    escalation_rate: float
    unhandled_rate: float


class RepairLoop:
    """Drive generate → execute → repair-feedback → retry.

    Args:
        executor: The sandbox to execute attempts in.
        generate: The SQL generator under test.
        max_attempts: Hard ceiling on attempts per question (≥1).
        escalation_policy: When given, evaluated on exhaustion with the
            caller-supplied evidence; the resulting case (possibly ``None``)
            is recorded on the report.
    """

    def __init__(
        self,
        executor: SandboxExecutor,
        generate: GeneratorFn,
        max_attempts: int = 3,
        escalation_policy: EscalationPolicy | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self._executor = executor
        self._generate = generate
        self._max_attempts = max_attempts
        self._escalation_policy = escalation_policy

    def run(
        self,
        question: str,
        prompt: str,
        escalation_evidence: EscalationEvidence | None = None,
    ) -> RepairReport:
        """Run the repair loop for one question."""
        attempts: list[RepairAttempt] = []
        last_error: str | None = None
        for attempt_no in range(1, self._max_attempts + 1):
            sql = self._generate(prompt, last_error)
            outcome = self._executor.execute(sql)
            attempts.append(
                RepairAttempt(
                    attempt_no=attempt_no,
                    sql=sql,
                    outcome=outcome,
                    feedback=last_error,
                )
            )
            if outcome.ok:
                repaired = attempt_no > 1
                return RepairReport(
                    question=question,
                    attempts=tuple(attempts),
                    repaired=repaired,
                    final_outcome=outcome,
                )
            last_error = outcome.error
        case: EscalatedCase | None = None
        if self._escalation_policy is not None and escalation_evidence is not None:
            case = self._escalation_policy.evaluate(question, escalation_evidence)
        return RepairReport(
            question=question,
            attempts=tuple(attempts),
            repaired=False,
            final_outcome=attempts[-1].outcome,
            escalated_case=case,
            exhausted=True,
        )


def repair_metrics(reports: Sequence[RepairReport]) -> RepairMetrics:
    """Aggregate repair metrics over per-question reports.

    ``repair_success_rate`` is conditioned on questions that *needed* repair
    (first attempt failed) — a loop that never fails has nothing to repair.
    ``unhandled_rate`` counts exhausted repairs where the escalation policy
    produced no case: the failure left the building with no declared owner.
    """
    n = len(reports)
    # A report with no attempts is malformed input, not a repair trajectory:
    # it contributes nothing rather than raising inside the aggregation.
    attempted = [r for r in reports if r.attempts]
    needed = [r for r in attempted if not r.attempts[0].outcome.ok]
    repaired = sum(1 for r in needed if r.repaired)
    exhausted = [r for r in attempted if r.exhausted]
    escalated = sum(1 for r in exhausted if r.escalated_case is not None)
    unhandled = len(exhausted) - escalated
    return RepairMetrics(
        n_questions=n,
        n_needed_repair=len(needed),
        repair_success_rate=(repaired / len(needed)) if needed else 1.0,
        mean_attempts=(sum(r.attempts_used for r in attempted) / n) if n else 0.0,
        escalation_rate=(escalated / len(exhausted)) if exhausted else 0.0,
        unhandled_rate=(unhandled / n) if n else 0.0,
    )
