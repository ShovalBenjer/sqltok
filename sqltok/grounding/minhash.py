"""Native MinHash for estimating Jaccard similarity between token sets.

A small, dependency-free MinHash implementation used for value grounding (the
CHESS-style idea of matching question mentions against database cell values,
reimplemented here rather than pulled from a library). Hash permutations are
generated from a fixed seed so signatures are fully deterministic.
"""

from __future__ import annotations

import numpy as np

# A Mersenne prime > 2**32, used as the modulus for universal hashing.
_MERSENNE_PRIME = (1 << 61) - 1
_MAX_HASH = (1 << 32) - 1


class MinHasher:
    """Compute MinHash signatures with ``num_perm`` permutations.

    Args:
        num_perm: Number of hash permutations (signature length). More perms
            give a lower-variance Jaccard estimate at higher cost.
        seed: Seed for the permutation coefficients; fixed for determinism.
    """

    def __init__(self, num_perm: int = 64, seed: int = 1) -> None:
        if num_perm <= 0:
            raise ValueError("num_perm must be positive")
        self.num_perm = num_perm
        rng = np.random.default_rng(seed)
        # a*x + b mod prime; a must be non-zero.
        self._a = rng.integers(1, _MERSENNE_PRIME, size=num_perm, dtype=np.uint64)
        self._b = rng.integers(0, _MERSENNE_PRIME, size=num_perm, dtype=np.uint64)

    def signature(self, tokens: set[str]) -> np.ndarray:
        """Return the ``(num_perm,)`` MinHash signature of a token set.

        An empty set yields an all-max signature (it shares no minima with any
        other set, so its estimated similarity to anything is 0).
        """
        if not tokens:
            return np.full(self.num_perm, _MAX_HASH, dtype=np.uint64)
        hashes = np.array([_token_hash(t) for t in tokens], dtype=np.uint64)
        # Outer combine: (a * h + b) mod prime, then min over tokens per perm.
        permuted = (
            np.outer(self._a, hashes) + self._b[:, None]
        ) % _MERSENNE_PRIME
        return permuted.min(axis=1).astype(np.uint64)

    @staticmethod
    def estimate_jaccard(sig_a: np.ndarray, sig_b: np.ndarray) -> float:
        """Estimate the Jaccard similarity of two sets from their signatures."""
        if sig_a.shape != sig_b.shape:
            raise ValueError("signatures must have equal length")
        return float(np.mean(sig_a == sig_b))


def _token_hash(token: str) -> int:
    """Stable 32-bit hash of a token (independent of PYTHONHASHSEED)."""
    import hashlib

    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=4).digest()
    return int.from_bytes(digest, "little") & _MAX_HASH
