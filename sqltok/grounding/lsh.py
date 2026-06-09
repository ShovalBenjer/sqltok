"""Banded LSH over MinHash signatures for fast candidate generation.

Each indexed item carries an arbitrary payload (here: which table/column/value a
string came from). A query returns items that collide in at least one band,
together with an estimated Jaccard similarity — the same locality-sensitive
hashing trick CHESS uses over database values, implemented natively.
"""

from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass

import numpy as np

from .minhash import MinHasher


@dataclass(slots=True)
class LSHCandidate:
    """A retrieved item: its payload and estimated Jaccard to the query."""

    payload: Hashable
    score: float


class LSHIndex:
    """A MinHash-banded LSH index mapping shingle sets to payloads.

    Args:
        num_perm: MinHash signature length. Must equal ``bands * rows``.
        bands: Number of LSH bands (more bands -> higher recall, more candidates).
        rows: Rows per band.
        seed: MinHash seed for determinism.
    """

    def __init__(
        self, *, num_perm: int = 64, bands: int = 32, rows: int = 2, seed: int = 1
    ) -> None:
        if bands * rows != num_perm:
            raise ValueError("bands * rows must equal num_perm")
        self.bands = bands
        self.rows = rows
        self._hasher = MinHasher(num_perm=num_perm, seed=seed)
        self._signatures: list[np.ndarray] = []
        self._payloads: list[Hashable] = []
        self._buckets: list[dict[bytes, list[int]]] = [dict() for _ in range(bands)]

    def add(self, shingles: set[str], payload: Hashable) -> None:
        """Index a shingle set under ``payload`` (no-op if the set is empty)."""
        if not shingles:
            return
        signature = self._hasher.signature(shingles)
        idx = len(self._signatures)
        self._signatures.append(signature)
        self._payloads.append(payload)
        for band, bucket_key in enumerate(self._band_keys(signature)):
            self._buckets[band].setdefault(bucket_key, []).append(idx)

    def query(self, shingles: set[str]) -> list[LSHCandidate]:
        """Return candidates colliding with ``shingles``, best score first.

        Ties are broken by ``repr(payload)`` so the ordering is deterministic.
        """
        if not shingles or not self._signatures:
            return []
        signature = self._hasher.signature(shingles)
        seen: set[int] = set()
        for band, bucket_key in enumerate(self._band_keys(signature)):
            seen.update(self._buckets[band].get(bucket_key, ()))
        results = [
            LSHCandidate(
                payload=self._payloads[idx],
                score=MinHasher.estimate_jaccard(signature, self._signatures[idx]),
            )
            for idx in seen
        ]
        results.sort(key=lambda c: (-c.score, repr(c.payload)))
        return results

    def _band_keys(self, signature: np.ndarray) -> list[bytes]:
        return [
            signature[b * self.rows : (b + 1) * self.rows].tobytes()
            for b in range(self.bands)
        ]
