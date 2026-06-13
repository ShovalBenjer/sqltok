"""Foreign-key Steiner connectivity for selected schemas.

A relevance-only selection can return tables with no join path between them,
which makes the LLM hallucinate joins. Following AutoLink's observation that
foreign keys are the "natural bridges" between relevant tables, we greedily add
the smallest set of intermediate (bridge) tables that makes the selection
join-connected — a heuristic Steiner-tree over the foreign-key graph — subject to
the remaining token budget.
"""

from __future__ import annotations

from collections import Counter, deque

from ..models import Schema
from .base import BudgetPacker


def expand_fk_neighbors(
    packer: BudgetPacker, seeds: list[str], *, min_links: int = 1
) -> list[str]:
    """Spend remaining budget on foreign-key neighbours of the seed tables.

    Gold queries almost always join a relevant table to one of its foreign-key
    neighbours, yet coverage selection stops once question mentions are covered,
    often leaving budget unused. This pulls in the one-hop FK neighbours of the
    seeds, prioritising tables connected to several seeds (junction tables) so
    join targets are added first. Budget-gated via :meth:`BudgetPacker.try_add`.

    Returns the list of neighbour tables added.
    """
    counts: Counter[str] = Counter()
    for seed in seeds:
        for neighbor in packer.schema.fk_neighbors(seed):
            if not packer.contains(neighbor):
                counts[neighbor] += 1
    added: list[str] = []
    for neighbor, links in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        if links < min_links:
            continue
        if packer.try_add(neighbor):
            added.append(neighbor)
    return added


def _adjacency(schema: Schema) -> dict[str, set[str]]:
    """Undirected foreign-key adjacency over all tables in the schema."""
    adj: dict[str, set[str]] = {name: set() for name in schema.tables}
    for name in schema.tables:
        for neighbor in schema.fk_neighbors(name):
            adj[name].add(neighbor)
            adj[neighbor].add(name)
    return adj


def _shortest_path(
    adj: dict[str, set[str]], sources: set[str], targets: set[str]
) -> list[str] | None:
    """BFS shortest path from any node in ``sources`` to any node in ``targets``.

    Returns the full node path (inclusive of endpoints), or ``None`` if the
    target set is unreachable. Neighbours are visited in sorted order so the
    chosen path is deterministic.
    """
    if sources & targets:
        node = sorted(sources & targets)[0]
        return [node]
    visited = set(sources)
    queue: deque[list[str]] = deque([n] for n in sorted(sources))
    while queue:
        path = queue.popleft()
        for neighbor in sorted(adj.get(path[-1], ())):
            if neighbor in visited:
                continue
            new_path = [*path, neighbor]
            if neighbor in targets:
                return new_path
            visited.add(neighbor)
            queue.append(new_path)
    return None


def connect_selection(packer: BudgetPacker) -> list[str]:
    """Add foreign-key bridge tables to make ``packer``'s selection connected.

    Greedily attaches each still-disconnected selected table to the growing
    connected component via its shortest foreign-key path, adding any
    intermediate tables that fit the budget. Mutates ``packer`` and returns the
    list of bridge tables that were added.
    """
    if len(packer.selected) <= 1:
        return []

    adj = _adjacency(packer.schema)
    remaining = list(packer.selected)
    connected: set[str] = {remaining.pop(0)}
    targets = set(remaining)
    bridges: list[str] = []

    while targets:
        path = _shortest_path(adj, connected, targets)
        if path is None:
            break  # disconnected in the FK graph; nothing to bridge
        endpoint = path[-1]
        intermediates = path[1:-1]
        added_ok = True
        for table in intermediates:
            if packer.contains(table):
                continue
            if packer.try_add(table):
                bridges.append(table)
            else:
                added_ok = False
                break
        if added_ok:
            connected.add(endpoint)
            connected.update(intermediates)
        targets.discard(endpoint)

    return bridges
