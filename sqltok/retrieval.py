"""Table retrieval for schema-context building.

The default retriever is keyword-based BM25 (via ``bm25s``) over a per-table
document built from the table name, column names, column descriptions, and a
sample of column values. An optional dense-embedding signal can be mixed in
behind a flag; it is **off by default** so the core package stays dependency
light and offline.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import bm25s
import numpy as np

from .models import Schema, Table

EmbeddingFn = Callable[[Sequence[str]], "np.ndarray"]


@dataclass(slots=True)
class RankedTable:
    """A table name with its fused retrieval score."""

    name: str
    score: float


def build_table_document(table: Table) -> str:
    """Build the searchable text document for a single table.

    Combines the table name, optional description, column names + descriptions,
    and any sampled column values into one bag-of-words string.
    """
    parts: list[str] = [table.name]
    if table.description:
        parts.append(table.description)
    for col in table.columns:
        parts.append(col.name)
        if col.description:
            parts.append(col.description)
        for value in col.sample_values:
            parts.append(str(value))
    return " ".join(parts)


class TableRetriever:
    """Rank tables by relevance to a natural-language question.

    Args:
        schema: The schema whose tables are indexed.
        use_embeddings: If ``True``, fuse a dense cosine-similarity score with
            BM25. Requires ``embedding_fn``.
        embedding_fn: A callable mapping a sequence of strings to an
            ``(n, d)`` float array of embeddings. Only used when
            ``use_embeddings`` is ``True``.
        embedding_weight: Blend weight in ``[0, 1]`` for the embedding score
            when fusing with the (min-max normalised) BM25 score.
    """

    def __init__(
        self,
        schema: Schema,
        *,
        use_embeddings: bool = False,
        embedding_fn: EmbeddingFn | None = None,
        embedding_weight: float = 0.5,
    ) -> None:
        if use_embeddings and embedding_fn is None:
            raise ValueError(
                "use_embeddings=True requires an embedding_fn. Install the "
                "'embeddings' extra and pass a callable, or leave embeddings off."
            )
        self.schema = schema
        self.use_embeddings = use_embeddings
        self.embedding_fn = embedding_fn
        self.embedding_weight = embedding_weight

        self._names: list[str] = schema.table_names()
        self._documents: list[str] = [
            build_table_document(schema.tables[name]) for name in self._names
        ]

        self._bm25: bm25s.BM25 | None = None
        if self._documents:
            corpus_tokens = bm25s.tokenize(
                self._documents, stopwords="en", show_progress=False
            )
            self._bm25 = bm25s.BM25()
            self._bm25.index(corpus_tokens, show_progress=False)

        self._doc_embeddings: np.ndarray | None = None
        if self.use_embeddings and self._documents and self.embedding_fn is not None:
            raw = np.asarray(self.embedding_fn(self._documents), dtype=float)
            self._doc_embeddings = _normalise(raw)

    def rank(self, question: str) -> list[RankedTable]:
        """Return all tables ranked by descending relevance to ``question``.

        Ranking is deterministic: ties (including the empty/all-zero case) are
        broken by table name so repeated calls yield identical ordering.
        """
        n = len(self._names)
        if n == 0:
            return []

        bm25_scores = self._bm25_scores(question)
        fused = bm25_scores
        use_emb = (
            self.use_embeddings
            and self._doc_embeddings is not None
            and self.embedding_fn is not None
        )
        if use_emb:
            emb_scores = self._embedding_scores(question)
            fused = (1.0 - self.embedding_weight) * _minmax(bm25_scores) + (
                self.embedding_weight * _minmax(emb_scores)
            )

        order = sorted(
            range(n), key=lambda i: (-float(fused[i]), self._names[i])
        )
        return [RankedTable(name=self._names[i], score=float(fused[i])) for i in order]

    def _bm25_scores(self, question: str) -> np.ndarray:
        if self._bm25 is None:
            return np.zeros(len(self._names), dtype=float)
        # return_ids=False yields a list of string-token lists; the query vocab
        # must not be re-mapped to fresh IDs or it won't align with the index.
        query_tokens = bm25s.tokenize(
            question, stopwords="en", show_progress=False, return_ids=False
        )
        if not query_tokens or not query_tokens[0]:
            return np.zeros(len(self._names), dtype=float)
        scores = self._bm25.get_scores(query_tokens[0])
        return np.asarray(scores, dtype=float)

    def _embedding_scores(self, question: str) -> np.ndarray:
        assert self.embedding_fn is not None and self._doc_embeddings is not None
        q = _normalise(np.asarray(self.embedding_fn([question]), dtype=float))
        return (self._doc_embeddings @ q[0]).astype(float)


def _minmax(scores: np.ndarray) -> np.ndarray:
    """Min-max normalise a score vector to ``[0, 1]`` (flat -> zeros)."""
    if scores.size == 0:
        return scores
    lo = float(scores.min())
    hi = float(scores.max())
    if hi - lo < 1e-12:
        return np.zeros_like(scores)
    return (scores - lo) / (hi - lo)


def _normalise(matrix: np.ndarray) -> np.ndarray:
    """L2-normalise rows of a 2D matrix for cosine similarity via dot product."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms
