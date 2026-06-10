"""Ground question mentions to schema elements and build coverage weights.

This is the signal that drives SQLTok's submodular selector. For a question we:

1. extract candidate mentions (n-grams + literals),
2. ground each mention to tables via name matches *and* sampled cell values
   (LSH over char-shingles), and
3. weight each grounded mention by a *self-supervised* inverse-document-frequency
   computed over this schema (a mention matching every table is uninformative;
   one matching a single table is highly discriminative).

The result is a ``(num_tables, num_mentions)`` coverage matrix plus a mention
weight vector — exactly the inputs a weighted-max-coverage objective needs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import numpy as np

from ..models import Schema
from .lsh import LSHIndex
from .text import char_shingles, extract_mentions

# Relative strength of the three grounding signals.
_KIND_WEIGHT = {"table": 1.0, "column": 1.0, "value": 0.9}
# A table is considered to "match" a mention above this affinity (for IDF df).
_MATCH_THRESHOLD = 0.18


@dataclass(slots=True)
class GroundedQuery:
    """Grounding of one question against a schema.

    Attributes:
        table_order: Table names indexing the rows of ``cover``.
        mentions: The grounded mention phrases (columns of ``cover``).
        cover: ``(num_tables, num_mentions)`` affinity matrix in ``[0, 1]``.
        weights: ``(num_mentions,)`` per-mention importance weights.
    """

    table_order: list[str]
    mentions: list[str]
    cover: np.ndarray
    weights: np.ndarray


class SchemaGrounding:
    """Build per-table coverage signals for questions over a fixed schema.

    Args:
        schema: The schema to ground against.
        max_values_per_column: Cap on distinct sampled values indexed per column.
        shingle_size: Character n-gram size for fuzzy matching.
        num_perm / bands / rows / seed: LSH/MinHash parameters (deterministic).
    """

    def __init__(
        self,
        schema: Schema,
        *,
        max_values_per_column: int = 20,
        shingle_size: int = 3,
        num_perm: int = 64,
        bands: int = 32,
        rows: int = 2,
        seed: int = 1,
    ) -> None:
        self.schema = schema
        self.shingle_size = shingle_size
        self._table_order = schema.table_names()
        self._table_index = {name: i for i, name in enumerate(self._table_order)}
        self._index = LSHIndex(num_perm=num_perm, bands=bands, rows=rows, seed=seed)
        self._build(max_values_per_column)

    def _build(self, max_values_per_column: int) -> None:
        for name in self._table_order:
            table = self.schema.tables[name]
            self._index.add(self._shingles(name), (name, "table"))
            for col in table.columns:
                self._index.add(self._shingles(col.name), (name, "column"))
                for value in col.sample_values[:max_values_per_column]:
                    sh = self._shingles(str(value))
                    if sh:
                        self._index.add(sh, (name, "value"))

    def _shingles(self, text: str) -> set[str]:
        return char_shingles(text, self.shingle_size)

    def ground(self, question: str) -> GroundedQuery:
        """Ground ``question`` and return its coverage matrix and weights."""
        mention_texts = extract_mentions(question)
        n_tables = len(self._table_order)

        kept_mentions: list[str] = []
        columns: list[np.ndarray] = []
        for mention in mention_texts:
            col = self._cover_column(mention, n_tables)
            if col is not None:
                kept_mentions.append(mention)
                columns.append(col)

        if not columns:
            cover = np.zeros((n_tables, 0), dtype=np.float32)
            weights = np.zeros((0,), dtype=np.float32)
            return GroundedQuery(self._table_order, [], cover, weights)

        cover = np.stack(columns, axis=1)
        weights = self._idf_weights(cover)
        return GroundedQuery(self._table_order, kept_mentions, cover, weights)

    def _cover_column(self, mention: str, n_tables: int) -> np.ndarray | None:
        """Return the per-table affinity column for one mention, or None."""
        shingles = self._shingles(mention)
        if not shingles:
            return None
        col = np.zeros(n_tables, dtype=np.float32)
        for cand in self._index.query(shingles):
            payload = cast("tuple[str, str]", cand.payload)
            table_name, kind = payload
            row = self._table_index[table_name]
            score = cand.score * _KIND_WEIGHT.get(kind, 1.0)
            # Exact value/name containment is a near-certain ground.
            if kind == "value" and cand.score >= 0.999:
                score = 1.0
            if score > col[row]:
                col[row] = min(score, 1.0)
        # Drop mentions that ground to nothing.
        if not np.any(col > 0.0):
            return None
        return col

    def _idf_weights(self, cover: np.ndarray) -> np.ndarray:
        """Self-supervised IDF: rarer mentions (fewer matching tables) weigh more."""
        n_tables = cover.shape[0]
        df = np.maximum((cover >= _MATCH_THRESHOLD).sum(axis=0), 1)
        # Smooth idf in [>0, ~log(n+1)], normalised so weights are comparable.
        weights = np.log1p(n_tables / df).astype(np.float32)
        return weights
