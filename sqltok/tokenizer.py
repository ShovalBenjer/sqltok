"""Real token counting via ``tiktoken``.

SQLTok never estimates token counts with heuristics such as ``len(text) / 4``;
every budget decision is made against an actual tokenizer so the hard ceiling is
meaningful for the target model.
"""

from __future__ import annotations

import tiktoken

DEFAULT_ENCODING = "cl100k_base"


class TokenCounter:
    """Wraps a ``tiktoken`` encoding and counts tokens.

    Args:
        encoding_name: Name of the ``tiktoken`` encoding to use. Defaults to
            ``cl100k_base`` (used by GPT-3.5/4 and a reasonable proxy elsewhere).
    """

    def __init__(self, encoding_name: str = DEFAULT_ENCODING) -> None:
        self.encoding_name = encoding_name
        self._encoding = tiktoken.get_encoding(encoding_name)

    def count(self, text: str) -> int:
        """Return the number of tokens in ``text``."""
        if not text:
            return 0
        return len(self._encoding.encode(text, disallowed_special=()))
