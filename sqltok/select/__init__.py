"""Schema-selection strategies (the ``SchemaSelector`` seam)."""

from __future__ import annotations

from .base import BudgetPacker, SchemaSelector
from .connect import connect_selection
from .coverage import CoverageSelector
from .greedy import RelevanceGreedySelector
from .stubs import AgenticSelector, RerankSelector

__all__ = [
    "SchemaSelector",
    "BudgetPacker",
    "CoverageSelector",
    "RelevanceGreedySelector",
    "RerankSelector",
    "AgenticSelector",
    "connect_selection",
]
