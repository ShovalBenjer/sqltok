"""Value-grounded submodular schema selection (SQLTok's default selector).

The objective is weighted maximum coverage of grounded question mentions::

    f(S) = sum_m  weight[m] * max_{T in S} cover[T, m]

which is monotone and submodular, so a greedy maximiser enjoys the classic
``(1 - 1/e)`` guarantee under a cardinality relaxation. We optimise the
*token-budgeted* (knapsack) version with the cost-benefit rule — pick the table
maximising marginal-gain / token-cost (cf. AdaGReS' redundancy-aware, token-
budgeted greedy) — accelerated with CELF lazy evaluation, and we also compare
against the best single table that fits (the Khuller-Moss-Sviridenko correction
that recovers the constant-factor knapsack guarantee). Finally we add foreign-key
Steiner bridges so the selection is join-connected.
"""

from __future__ import annotations

import heapq

import numpy as np

from ..context import SchemaContext
from ..grounding import SchemaGrounding
from ..grounding.affinity import GroundedQuery
from ..models import Schema
from ..tokenizer import TokenCounter
from .base import BudgetPacker
from .connect import connect_selection, expand_fk_neighbors


class CoverageSelector:
    """Select schema tables by budgeted submodular mention coverage.

    Args:
        schema: The schema to select from.
        grounding: A prebuilt :class:`SchemaGrounding` over ``schema``. If
            ``None``, one is constructed with default parameters.
    """

    name = "coverage"

    def __init__(
        self,
        schema: Schema,
        *,
        grounding: SchemaGrounding | None = None,
        fk_min_links: int = 1,
    ) -> None:
        self.schema = schema
        self.grounding = grounding if grounding is not None else SchemaGrounding(schema)
        # Minimum number of selected tables an FK neighbour must link to before it
        # is pulled in. 1 maximises recall, 2 favours precision and token savings.
        self.fk_min_links = fk_min_links

    def select(
        self,
        question: str,
        *,
        token_budget: int,
        counter: TokenCounter,
        include_sample_rows: bool = True,
        fk_expand: bool = True,
    ) -> SchemaContext:
        """Build a budgeted, join-connected schema context for ``question``."""
        grounded = self.grounding.ground(question)
        packer = BudgetPacker(
            self.schema,
            token_budget=token_budget,
            counter=counter,
            include_sample_rows=include_sample_rows,
        )

        if grounded.mentions:
            self._greedy_cover(grounded, packer)
        else:
            self._fallback_pack(packer)

        fk_added: list[str] = []
        bridges: list[str] = []
        if fk_expand:
            # Spend leftover budget on FK neighbours of the covered tables
            # (where join targets live), then bridge any disjoint components.
            seeds = list(packer.selected)
            fk_added = expand_fk_neighbors(packer, seeds, min_links=self.fk_min_links)
            bridges = connect_selection(packer)

        text = packer.render()
        total_weight = float(grounded.weights.sum()) if grounded.weights.size else 0.0
        covered = self._covered_weight(grounded, packer.selected) if total_weight else 0.0
        return SchemaContext(
            text=text,
            tables=list(packer.selected),
            token_count=counter.count(text),
            budget=token_budget,
            encoding_name=counter.encoding_name,
            selector=self.name,
            bridge_tables=bridges,
            fk_expanded=fk_added,
            covered_weight=covered / total_weight if total_weight else 0.0,
        )

    # -- internals ------------------------------------------------------------

    def _greedy_cover(self, grounded: GroundedQuery, packer: BudgetPacker) -> None:
        """CELF cost-benefit greedy maximisation of the coverage objective."""
        table_order = grounded.table_order
        cover = grounded.cover  # (T, M)
        weights = grounded.weights  # (M,)
        current = np.zeros(weights.shape, dtype=np.float32)

        def marginal(row_idx: int) -> float:
            gain = weights * np.maximum(cover[row_idx] - current, 0.0)
            return float(gain.sum())

        costs = {name: max(packer.standalone_cost(name), 1) for name in table_order}

        # Initialise the lazy heap with first-round ratios (negated for min-heap).
        heap: list[tuple[float, str, int]] = []
        for idx, name in enumerate(table_order):
            gain = marginal(idx)
            if gain > 0.0:
                heapq.heappush(heap, (-gain / costs[name], name, 0))

        index_of = {name: i for i, name in enumerate(table_order)}
        round_no = 0
        dead: set[str] = set()
        best_single = self._best_single_table(grounded, packer, costs)

        while heap:
            neg_ratio, name, stamp = heapq.heappop(heap)
            if name in dead or packer.contains(name):
                continue
            if stamp == round_no:
                # Ratio is current and maximal -> commit it (cost-benefit pick).
                if packer.try_add(name):
                    current = np.maximum(current, cover[index_of[name]])
                    round_no += 1
                else:
                    dead.add(name)  # never fits from here on
            else:
                gain = marginal(index_of[name])
                if gain <= 0.0:
                    continue
                heapq.heappush(heap, (-gain / costs[name], name, round_no))

        self._maybe_prefer_single(grounded, packer, best_single)

    def _best_single_table(
        self, grounded: GroundedQuery, packer: BudgetPacker, costs: dict[str, int]
    ) -> tuple[str, float] | None:
        """Highest-coverage single table that fits the budget (KMS comparison)."""
        weights = grounded.weights
        cover = grounded.cover
        best: tuple[str, float] | None = None
        for idx, name in enumerate(grounded.table_order):
            if packer.standalone_cost(name) > packer.token_budget:
                continue
            value = float((weights * cover[idx]).sum())
            if best is None or value > best[1] or (value == best[1] and name < best[0]):
                best = (name, value)
        return best

    def _maybe_prefer_single(
        self,
        grounded: GroundedQuery,
        packer: BudgetPacker,
        best_single: tuple[str, float] | None,
    ) -> None:
        """If a single table beats the greedy set on coverage, prefer it."""
        if best_single is None:
            return
        greedy_value = self._covered_weight(grounded, packer.selected)
        if best_single[1] > greedy_value + 1e-9:
            packer.selected.clear()
            packer.sample_flags.clear()
            packer.try_add(best_single[0])

    def _covered_weight(self, grounded: GroundedQuery, selected: list[str]) -> float:
        if not grounded.weights.size or not selected:
            return 0.0
        index_of = {name: i for i, name in enumerate(grounded.table_order)}
        rows = [grounded.cover[index_of[n]] for n in selected if n in index_of]
        if not rows:
            return 0.0
        covered = np.max(np.stack(rows, axis=0), axis=0)
        return float((grounded.weights * covered).sum())

    def _fallback_pack(self, packer: BudgetPacker) -> None:
        """No grounding signal: pack the smallest tables first to fill budget."""
        by_cost = sorted(
            packer.schema.table_names(), key=lambda n: (packer.standalone_cost(n), n)
        )
        for name in by_cost:
            packer.try_add(name)
