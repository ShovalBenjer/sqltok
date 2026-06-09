"""The public entry point: :class:`SchemaBudgetManager`.

A manager wraps a parsed schema, a BM25 (optionally hybrid) retriever, and a
``tiktoken`` token counter, and turns a natural-language question plus a token
budget into a compact, prompt-ready schema context.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np

from .budget import build_budgeted_context
from .context import SchemaContext
from .ddl import parse_ddl
from .introspect import introspect_sqlite
from .models import Schema
from .retrieval import TableRetriever
from .tokenizer import DEFAULT_ENCODING, TokenCounter

EmbeddingFn = Callable[[Sequence[str]], "np.ndarray"]


class SchemaBudgetManager:
    """Retrieve a token-budgeted schema context for a Text2SQL prompt.

    Construct one via :meth:`from_sqlite` or :meth:`from_ddl`, then call
    :meth:`build_context` per question. The manager performs no network I/O; the
    LLM is only ever involved downstream in your own prompt.

    Args:
        schema: The schema to serve contexts from.
        encoding_name: ``tiktoken`` encoding used for all token counting.
        use_embeddings: Enable hybrid dense retrieval (off by default to keep the
            core dependency-light). Requires ``embedding_fn``.
        embedding_fn: Callable mapping strings to embedding vectors; only used
            when ``use_embeddings`` is ``True``.
        embedding_weight: Blend weight for the embedding score during fusion.
    """

    def __init__(
        self,
        schema: Schema,
        *,
        encoding_name: str = DEFAULT_ENCODING,
        use_embeddings: bool = False,
        embedding_fn: EmbeddingFn | None = None,
        embedding_weight: float = 0.5,
    ) -> None:
        self.schema = schema
        self.counter = TokenCounter(encoding_name)
        self.retriever = TableRetriever(
            schema,
            use_embeddings=use_embeddings,
            embedding_fn=embedding_fn,
            embedding_weight=embedding_weight,
        )

    # -- constructors ---------------------------------------------------------

    @classmethod
    def from_sqlite(
        cls,
        db_path: str | Path,
        *,
        sample_rows: int = 3,
        encoding_name: str = DEFAULT_ENCODING,
        use_embeddings: bool = False,
        embedding_fn: EmbeddingFn | None = None,
        embedding_weight: float = 0.5,
    ) -> SchemaBudgetManager:
        """Build a manager by introspecting a SQLite database file.

        Args:
            db_path: Path to the SQLite database.
            sample_rows: Rows to sample per table for values/example rows.
            encoding_name: ``tiktoken`` encoding name.
            use_embeddings: Enable hybrid dense retrieval.
            embedding_fn: Embedding callable (required if ``use_embeddings``).
            embedding_weight: Blend weight for the embedding score.
        """
        schema = introspect_sqlite(db_path, sample_rows=sample_rows)
        return cls(
            schema,
            encoding_name=encoding_name,
            use_embeddings=use_embeddings,
            embedding_fn=embedding_fn,
            embedding_weight=embedding_weight,
        )

    @classmethod
    def from_ddl(
        cls,
        ddl: str,
        *,
        dialect: str | None = None,
        encoding_name: str = DEFAULT_ENCODING,
        use_embeddings: bool = False,
        embedding_fn: EmbeddingFn | None = None,
        embedding_weight: float = 0.5,
    ) -> SchemaBudgetManager:
        """Build a manager from raw ``CREATE TABLE`` DDL.

        Args:
            ddl: One or more ``CREATE TABLE`` statements.
            dialect: Optional ``sqlglot`` dialect name.
            encoding_name: ``tiktoken`` encoding name.
            use_embeddings: Enable hybrid dense retrieval.
            embedding_fn: Embedding callable (required if ``use_embeddings``).
            embedding_weight: Blend weight for the embedding score.
        """
        schema = parse_ddl(ddl, dialect=dialect)
        return cls(
            schema,
            encoding_name=encoding_name,
            use_embeddings=use_embeddings,
            embedding_fn=embedding_fn,
            embedding_weight=embedding_weight,
        )

    # -- core API -------------------------------------------------------------

    def build_context(
        self,
        question: str,
        *,
        token_budget: int = 2000,
        include_sample_rows: bool = True,
        fk_expand: bool = True,
    ) -> SchemaContext:
        """Build a token-budgeted schema context for ``question``.

        Args:
            question: The natural-language question to retrieve schema for.
            token_budget: Hard ceiling on schema-context tokens. The returned
                ``token_count`` is guaranteed not to exceed this.
            include_sample_rows: Attach one example row per included table when
                it fits within budget.
            fk_expand: Pull in foreign-key neighbours of selected tables if the
                budget allows.

        Returns:
            A :class:`SchemaContext` with the rendered text, selected tables, and
            measured token count.
        """
        if token_budget <= 0:
            raise ValueError("token_budget must be positive")
        ranked = self.retriever.rank(question)
        return build_budgeted_context(
            self.schema,
            ranked,
            token_budget=token_budget,
            counter=self.counter,
            include_sample_rows=include_sample_rows,
            fk_expand=fk_expand,
        )

    def full_schema_text(self, *, include_sample_rows: bool = True) -> str:
        """Return the entire schema as DDL (the benchmark *baseline* dump)."""
        return self.schema.render_full_ddl(include_sample_rows=include_sample_rows)

    def count_tokens(self, text: str) -> int:
        """Count tokens in ``text`` with this manager's encoding."""
        return self.counter.count(text)
