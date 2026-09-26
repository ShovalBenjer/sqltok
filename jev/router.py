"""jev router: cost/latency-aware model routing.

Priority: local small LMs (Ollama) -> free tiers (GitHub Models, other free APIs)
-> paid escalation only when the task needs it.

Hardening (ADR-0009, "SLM swarm = asymmetric leaf executors"):
- Every routing decision is appended to ``jev/decisions.jsonl`` (kept-local
  reason + confidence included), so the escalation threshold can be calibrated.
- An uncertainty escalation threshold routes hard/uncertain tasks to a more
  capable route instead of keeping them local.
- Every route is schema-checked before it is returned.
- INVARIANT: the router ROUTES, it never JUDGES. It never refuses, vetoes, or
  gates a task on content grounds; uncertain or hard tasks are ESCALATED, never
  blocked. The only failure is ``RuntimeError`` when no backend is available
  (availability, not judgment).

Usage:
    from jev.router import route
    r = route("summarize this log")
    print(r.name, r.model, r.base_url)
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

#: Complexity at/above which a non-"free" budget escalates past the local tier.
#: Named (was a magic 0.55) so it can be calibrated against decisions.jsonl.
ESCALATE_AT = 0.55

_ROUTE_KINDS = ("ollama", "github-models", "free-api", "paid")


@dataclass
class Route:
    name: str
    kind: str  # ollama | github-models | free-api | paid
    model: str
    base_url: str
    api_key_env: str | None
    cost_per_1k: float
    latency_ms_p50: int
    max_context: int
    available: bool = field(default=False, compare=False)


class RouteSchemaError(ValueError):
    """A route failed its schema check; never returned to callers."""


def _decisions_log_path() -> Path:
    override = os.getenv("JEV_DECISIONS_LOG")
    if override:
        return Path(override)
    return Path(__file__).with_name("decisions.jsonl")


def _log_decision(
    *, task: str, complexity: float, confidence: float, reason: str, route: Route, escalated: bool
) -> None:
    """Append one decision record. Append-only; the task text is never stored."""
    record = {
        "ts": datetime.now(UTC).isoformat(),
        "task_sha256": hashlib.sha256(task.encode("utf-8")).hexdigest(),
        "task_len": len(task),
        "complexity": round(complexity, 3),
        "confidence": confidence,
        "reason": reason,
        "route": route.name,
        "route_kind": route.kind,
        "escalated": escalated,
    }
    path = _decisions_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _check_route_schema(route: Route) -> None:
    """Validate a route before it is handed to a caller (schema-check on outputs)."""
    problems = []
    if not route.name or not isinstance(route.name, str):
        problems.append("name must be a non-empty string")
    if route.kind not in _ROUTE_KINDS:
        problems.append(f"kind must be one of {_ROUTE_KINDS}, got {route.kind!r}")
    if not route.model or not isinstance(route.model, str):
        problems.append("model must be a non-empty string")
    if not route.base_url or not route.base_url.startswith(("http://", "https://")):
        problems.append(f"base_url must be an http(s) URL, got {route.base_url!r}")
    if route.cost_per_1k < 0:
        problems.append("cost_per_1k must be >= 0")
    if route.latency_ms_p50 <= 0:
        problems.append("latency_ms_p50 must be > 0")
    if route.max_context <= 0:
        problems.append("max_context must be > 0")
    if problems:
        raise RouteSchemaError(f"route {route.name!r} failed schema check: " + "; ".join(problems))


def _ollama_alive(url: str, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/tags", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def default_routes() -> list[Route]:
    return [
        Route(
            "ollama-local",
            "ollama",
            os.getenv("JEV_LOCAL_MODEL", "qwen2.5:7b"),
            "http://localhost:11434",
            None,
            0.0,
            400,
            32768,
        ),
        Route(
            "github-models",
            "github-models",
            os.getenv("JEV_GH_MODEL", "gpt-4o-mini"),
            "https://models.github.ai/inference",
            "JEV_MODEL_TOKEN",
            0.0,
            1200,
            128000,
        ),
    ]


def estimate_complexity(task: str) -> float:
    """0..1 heuristic: short/simple tasks stay local, hard ones escalate."""
    t = task.lower()
    score = min(len(task) / 4000, 1.0) * 0.4
    hard = (
        "prove",
        "security",
        "architecture",
        "refactor",
        "distributed",
        "concurrency",
        "formal",
        "cryptograph",
    )
    score += 0.15 * sum(1 for m in hard if m in t)
    return min(score, 1.0)


def estimate_confidence(complexity: float) -> float:
    """0..1: distance from the escalation boundary, scaled.

    Deliberately heuristic — it is logged with every decision so the escalation
    threshold can be calibrated against real traffic (ADR-0009).
    """
    gap = abs(complexity - ESCALATE_AT)
    return round(min(max(gap / 0.25, 0.05), 1.0), 3)


def route(task: str, budget: str = "free") -> Route:
    """Pick the cheapest route that can plausibly handle the task.

    budget: "free" (never paid), "balanced" (prefer free, allow paid when hard),
            "max-quality" (best capable route regardless of cost).

    INVARIANT (ADR-0009): the router routes but never judges or gates. It never
    raises on task content — only ``RuntimeError`` when no backend is available.
    """
    complexity = estimate_complexity(task)
    confidence = estimate_confidence(complexity)
    routes = [dataclasses.replace(r) for r in default_routes()]
    for r in routes:
        _check_route_schema(r)

    local, gh = routes[0], routes[1]
    local.available = _ollama_alive(local.base_url)
    gh.available = bool(os.getenv(gh.api_key_env or ""))

    escalate = budget != "free" and complexity >= ESCALATE_AT
    ordered = [gh, local] if escalate else [local, gh]
    chosen = next((r for r in ordered if r.available), None)
    if chosen is None:
        # Availability failure, never a content judgment.
        raise RuntimeError("no model route available: start Ollama or set JEV_MODEL_TOKEN")

    if escalate:
        reason = "escalated-uncertain" if chosen is gh else "escalation-requested-no-route"
    elif chosen is gh:
        reason = "free-tier-fallback-local-down"
    elif complexity < ESCALATE_AT:
        reason = "kept-local-simple"
    else:
        reason = "kept-local-budget-free"

    _log_decision(
        task=task,
        complexity=complexity,
        confidence=confidence,
        reason=reason,
        route=chosen,
        escalated=escalate and chosen is gh,
    )
    return chosen
