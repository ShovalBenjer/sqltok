"""Adversarial test battery for the tokenizer.

Grounded in the security-research note (section 3.2): a tokenizer is exactly
where the defense against homoglyph, bidi, zero-width, and role-token attacks
lives. These tests pin the neutralization behavior of ``TokenCounter`` \u2014
``disallowed_special=()`` means role-token strings are encoded as plain text,
never as special tokens \u2014 so a future change cannot silently reopen the hole.

Tests only: no production code is added or changed here.
"""

from __future__ import annotations

import unicodedata

import pytest
import tiktoken

from sqltok.tokenizer import DEFAULT_ENCODING, TokenCounter

ENC = tiktoken.get_encoding(DEFAULT_ENCODING)

# Invisible / direction-control / otherwise tricky Unicode. None of these may
# crash the tokenizer, and each must tokenize deterministically.
ADVERSARIAL_BATTERY = [
    "\u200b",  # zero-width space U+200B
    "\u200c",  # zero-width non-joiner U+200C
    "\u2060",  # word joiner U+2060
    "\u202e",  # right-to-left override U+202E
    "\u202a",  # left-to-right embedding U+202A
    "\u202b",  # right-to-left embedding U+202B
    "\u202c",  # pop directional formatting U+202C
    "\u2066",  # left-to-right isolate U+2066
    "\u2069",  # pop directional isolate U+2069
    "\ufeff",  # byte-order mark U+FEFF
    "\u2028",  # line separator U+2028
    "\u2029",  # paragraph separator U+2029
    "\U000e0001",  # tag character U+E0001
    "\ufb01",  # ligature U+FB01 (NFKC -> "fi")
    "\u0430",  # Cyrillic small a U+0430 (homoglyph of Latin "a")
    "\ud800",  # lone surrogate
    "\ud83d",  # lone high surrogate (half of an emoji)
    "\uff01",  # fullwidth exclamation U+FF01
    "\ufe0f",  # variation selector U+FE0F
]


@pytest.fixture
def counter() -> TokenCounter:
    return TokenCounter()


def test_empty_counts_zero(counter: TokenCounter) -> None:
    assert counter.count("") == 0


def test_no_crash_on_adversarial_battery(counter: TokenCounter) -> None:
    for text in ADVERSARIAL_BATTERY:
        first = counter.count(text)
        assert isinstance(first, int) and first >= 0
        assert counter.count(text) == first, f"nondeterministic count for {text!r}"


def test_role_token_strings_are_plain_text(counter: TokenCounter) -> None:
    """Role-token strings must never act as special tokens.

    ``<|endoftext|>`` IS a special token id in cl100k_base; with
    ``disallowed_special=()`` it must still encode as ordinary text (more than
    one token), so injected role tokens cannot hijack tokenization or budgets.
    """
    for text in ("<|endoftext|>", "<|im_start|>", "system:", "assistant:"):
        ids = ENC.encode(text, disallowed_special=())
        assert len(ids) > 1, f"{text!r} collapsed to a special token"
        assert counter.count(text) == len(ids)


def test_homoglyphs_do_not_collapse(counter: TokenCounter) -> None:
    """Visually identical strings from different scripts tokenize differently.

    A Cyrillic '\u0430' must never be interchangeable with a Latin 'a' at the token
    layer \u2014 otherwise homoglyph substitution would be invisible to budgets.
    """
    cyrillic_a = ENC.encode("\u0430", disallowed_special=())
    latin_a = ENC.encode("a", disallowed_special=())
    assert cyrillic_a != latin_a
    assert counter.count("\u0430") == len(cyrillic_a) > 0
    # Mixed-script SQL still tokenizes deterministically.
    mixed = "SELECT \u0430 FROM t"
    assert counter.count(mixed) == counter.count(mixed) >= 0


def test_normalization_changes_tokenization(counter: TokenCounter) -> None:
    """Documents why Unicode normalization (security doc, section 3.2) must run
    BEFORE tokenization: NFKC can change the token count."""
    ligature = "\ufb01"
    normalized = unicodedata.normalize("NFKC", ligature)
    assert normalized == "fi"
    assert counter.count(ligature) != counter.count(normalized)


def test_bidi_characters_consume_budget(counter: TokenCounter) -> None:
    """Bidi override characters are real tokens -- wrapping text in them cannot
    hide it from the budget, and cannot crash the counter."""
    visible = "select * from users"
    wrapped = "\u202e" + visible
    assert counter.count(wrapped) > counter.count(visible)
    assert counter.count("\u202e") > 0


def test_tricky_decodings_do_not_crash(counter: TokenCounter) -> None:
    # Text that survived lossy decoding (U+FFFD replacement chars).
    lossy = "SELECT \ufffd FROM t".encode("utf-8", "replace").decode("utf-8")
    assert counter.count(lossy) > 0
    # Whitespace-only strings are fine.
    assert counter.count("   \t\n") >= 0


def test_count_is_deterministic(counter: TokenCounter) -> None:
    text = "SELECT id, name FROM customers WHERE region = 'North'"
    assert counter.count(text) == counter.count(text) > 0
