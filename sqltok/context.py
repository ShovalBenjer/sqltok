"""The result object returned by :meth:`SchemaBudgetManager.build_context`.

A context carries its protocol outcome as a first-class
:class:`~sqltok.escalation.DecisionState`: the automated protocol either
``SERVED`` the context or ``ESCALATED`` it to the declared arbiter along a
declared :class:`~sqltok.escalation.EscalationPath`. Escalation is a planned
branch of the protocol, never a failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .escalation import DecisionState, EscalatedCase


@dataclass(slots=True)
class SchemaContext:
    """A budget-constrained schema context ready to drop into an LLM prompt.

    Attributes:
        text: The compact ``CREATE TABLE``-style schema string.
        tables: Selected table names, in rendered order.
        token_count: Real token count of ``text`` (measured with ``tiktoken``).
        budget: The token budget the context was built against.
        encoding_name: The ``tiktoken`` encoding used to measure tokens.
        selector: Name of the selection strategy that produced this context.
        bridge_tables: Tables added purely to make the selection join-connected
            (foreign-key Steiner bridges), not because they were relevant.
        fk_expanded: Tables added by plain foreign-key expansion (baseline
            selector); kept for backwards compatibility.
        covered_weight: Fraction of total grounded mention weight covered by the
            selection (``0.0`` for selectors that do not compute coverage).
        decision_state: First-class protocol outcome. ``SERVED`` (default) means
            the automated protocol produced this context; ``ESCALATED`` means a
            declared escalation path fired and the case was routed to the
            arbiter named on :attr:`escalation`.
        escalation: The :class:`~sqltok.escalation.EscalatedCase` record when
            :attr:`decision_state` is ``ESCALATED``, else ``None``. The two are
            kept consistent by :meth:`__post_init__`: an escalation record
            without the ``ESCALATED`` state (or vice versa) raises.
        grounded_mentions: Number of grounded mentions for the question, as
            reported by grounding-based selectors; ``-1`` (unknown) when the
            selector does not ground.
        top_scores: Ranked per-table grounding scores, best first, as reported
            by grounding-based selectors; empty when unreported.
        coverage_reported: Whether :attr:`covered_weight` was actually computed
            by the selector. ``False`` distinguishes "selector reports no
            coverage" from a genuine ``0.0``.
    """

    text: str
    tables: list[str]
    token_count: int
    budget: int
    encoding_name: str
    selector: str = ""
    bridge_tables: list[str] = field(default_factory=list)
    fk_expanded: list[str] = field(default_factory=list)
    covered_weight: float = 0.0
    decision_state: DecisionState = DecisionState.SERVED
    escalation: EscalatedCase | None = None
    grounded_mentions: int = -1
    top_scores: tuple[float, ...] = ()
    coverage_reported: bool = False

    def __post_init__(self) -> None:
        escalated = self.decision_state is DecisionState.ESCALATED
        if (self.escalation is not None) != escalated:
            raise ValueError(
                "escalation record and decision_state disagree: an ESCALATED "
                "context must carry its EscalatedCase, and a context carrying "
                "one must be ESCALATED"
            )

    def __str__(self) -> str:
        return self.text
