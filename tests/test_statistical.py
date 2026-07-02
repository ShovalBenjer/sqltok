"""Statistical tests for the MinHash and LSH primitives.

The docs claim MinHash gives an unbiased estimate of Jaccard similarity and that
LSH retrieves similar items. These tests check those claims numerically over many
random set pairs with fixed seeds, so they are deterministic.
"""

from __future__ import annotations

import random

from sqltok.grounding.lsh import LSHIndex
from sqltok.grounding.minhash import MinHasher


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def _random_pair(rng: random.Random, universe: int = 400) -> tuple[set[str], set[str]]:
    size_a = rng.randint(5, 60)
    size_b = rng.randint(5, 60)
    a = {str(x) for x in rng.sample(range(universe), size_a)}
    b = {str(x) for x in rng.sample(range(universe), size_b)}
    return a, b


def test_minhash_is_unbiased_on_average() -> None:
    hasher = MinHasher(num_perm=256, seed=1)
    rng = random.Random(0)
    errors = []
    for _ in range(200):
        a, b = _random_pair(rng)
        est = MinHasher.estimate_jaccard(hasher.signature(a), hasher.signature(b))
        errors.append(est - _jaccard(a, b))
    mean_error = sum(errors) / len(errors)
    mean_abs_error = sum(abs(e) for e in errors) / len(errors)
    # Unbiased: mean signed error near zero. Low variance: small mean abs error.
    assert abs(mean_error) < 0.02
    assert mean_abs_error < 0.05


def test_minhash_extremes_are_exact() -> None:
    hasher = MinHasher(num_perm=128, seed=3)
    a = {"x", "y", "z"}
    assert MinHasher.estimate_jaccard(hasher.signature(a), hasher.signature(a)) == 1.0
    disjoint = MinHasher.estimate_jaccard(
        hasher.signature({"a", "b"}), hasher.signature({"c", "d"})
    )
    assert disjoint < 0.1


def test_minhash_estimate_is_monotone_in_true_jaccard() -> None:
    hasher = MinHasher(num_perm=256, seed=2)
    base = {str(x) for x in range(100)}
    # Increasing overlap fractions should give increasing mean estimates.
    prev = -1.0
    for keep in (10, 30, 50, 70, 90):
        overlap = {str(x) for x in range(keep)}
        extra = {str(x) for x in range(100, 200 - keep)}
        other = overlap | extra
        est = MinHasher.estimate_jaccard(hasher.signature(base), hasher.signature(other))
        assert est >= prev - 0.05  # allow small estimator noise
        prev = est


def test_lsh_retrieves_similar_items() -> None:
    index = LSHIndex(num_perm=64, bands=32, rows=2, seed=1)
    index.add({str(x) for x in range(50)}, "almost_query")   # ~98% overlap
    index.add({str(x) for x in range(200, 260)}, "unrelated")
    query = {str(x) for x in range(1, 50)}
    payloads = [c.payload for c in index.query(query)]
    assert "almost_query" in payloads
    # The near-duplicate should outrank the unrelated item if both appear.
    if "unrelated" in payloads:
        assert payloads.index("almost_query") < payloads.index("unrelated")
