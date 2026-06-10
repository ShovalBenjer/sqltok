"""Tokenisation helpers for mention extraction and value shingling."""

from __future__ import annotations

import re

_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
_QUOTED_RE = re.compile(r"'([^']+)'|\"([^\"]+)\"")

# Small, SQL/English stopword set. Deliberately tiny so we keep schema-ish words
# like "name", "date", "id" that often matter for linking.
STOPWORDS = frozenset(
    """
    a an and are as at be by for from how in into is it of on or that the to
    was what when where which who whose will with your you me my our their show
    list give find get all each per
    """.split()
)


def normalise(text: str) -> str:
    """Lowercase and collapse non-alphanumerics in a single token/value."""
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def word_tokens(text: str) -> list[str]:
    """Split text into lowercase word tokens (snake_case is split on ``_``)."""
    tokens: list[str] = []
    for match in _WORD_RE.findall(text.lower()):
        tokens.extend(p for p in match.split("_") if p)
    return tokens


def char_shingles(text: str, n: int = 3) -> set[str]:
    """Return the set of character ``n``-grams of a normalised string.

    Character shingles give fuzzy matching robust to plurals/typos/casing, which
    is what we want when grounding a question mention to a database cell value.
    """
    norm = normalise(text)
    if not norm:
        return set()
    if len(norm) <= n:
        return {norm}
    return {norm[i : i + n] for i in range(len(norm) - n + 1)}


def extract_mentions(question: str, max_ngram: int = 3) -> list[str]:
    """Extract candidate mention phrases from a natural-language question.

    Produces quoted literals plus contiguous 1..``max_ngram`` word phrases with
    stopwords trimmed from the edges. Order is preserved and duplicates removed.
    """
    mentions: list[str] = []
    seen: set[str] = set()

    def add(phrase: str) -> None:
        key = phrase.lower().strip()
        if key and key not in seen:
            seen.add(key)
            mentions.append(phrase)

    for quoted in _QUOTED_RE.findall(question):
        literal = quoted[0] or quoted[1]
        add(literal)

    tokens = word_tokens(question)
    n_tokens = len(tokens)
    for size in range(1, max_ngram + 1):
        for start in range(n_tokens - size + 1):
            window = tokens[start : start + size]
            # Trim leading/trailing stopwords from multi-word phrases.
            while len(window) > 1 and window[0] in STOPWORDS:
                window = window[1:]
            while len(window) > 1 and window[-1] in STOPWORDS:
                window = window[:-1]
            if len(window) == 1 and window[0] in STOPWORDS:
                continue
            add(" ".join(window))
    return mentions
