#!/usr/bin/env python3
"""Lint a social post against the house style.

Fails (exit code 1) on em-dashes, "not X but Y" constructions, AI-slop
vocabulary, emoji, and exclamation overuse. Reads a file argument or stdin.

Usage:
    python lint_post.py draft.txt
    echo "..." | python lint_post.py
"""

from __future__ import annotations

import re
import sys
import unicodedata

SLOP_TERMS = [
    "delve", "leverage", "seamless", "seamlessly", "robust", "powerful",
    "revolutionary", "game-changer", "game changer", "unlock", "unlocks",
    "supercharge", "tapestry", "testament", "realm", "dive in", "deep dive",
    "elevate", "harness", "embark", "navigate the", "in the world of",
    "when it comes to", "at the end of the day", "paradigm", "needle-moving",
    "thrilled to announce", "excited to share", "the possibilities are endless",
    "stay tuned", "watch this space", "in today's fast-paced",
]

# "not X but Y" family. Catches "it's", "it is", "its", and the spaced forms.
_PRON = r"(it'?s|it is|its|this is|that is)"
NOT_X_BUT_Y = [
    re.compile(rf"\bnot just\b.{{0,70}}?\b(but|{_PRON})\b", re.I),
    re.compile(r"\bnot only\b.{0,70}?\bbut\b", re.I),
    re.compile(rf"\b{_PRON} not (just )?about\b.{{0,70}}?\babout\b", re.I),
    re.compile(r"\bisn'?t just\b", re.I),
    re.compile(rf"\b{_PRON} not just\b", re.I),
    re.compile(rf"\bnot (just )?a\b.{{0,50}}?,\s*{_PRON}\b", re.I),
]


def find_emoji(text: str) -> list[str]:
    found = []
    for ch in text:
        if ord(ch) < 128:
            continue
        if ord(ch) >= 0x1F000 or unicodedata.category(ch) == "So":
            found.append(ch)
    return found


def lint(text: str) -> list[str]:
    issues: list[str] = []

    if "—" in text or "–" in text:
        issues.append("em-dash or en-dash found. Use a period or comma.")

    for pat in NOT_X_BUT_Y:
        m = pat.search(text)
        if m:
            issues.append(f'"not X but Y" construction: {m.group(0)!r}')

    low = text.lower()
    for term in SLOP_TERMS:
        if term in low:
            issues.append(f"AI-slop term: {term!r}")

    emoji = find_emoji(text)
    if emoji:
        issues.append(f"emoji or decorative symbol: {''.join(sorted(set(emoji)))}")

    if text.count("!") > 1:
        issues.append("more than one exclamation mark")
    if "!!" in text:
        issues.append("double exclamation mark")

    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique = [i for i in issues if not (i in seen or seen.add(i))]
    return unique


def main() -> int:
    if len(sys.argv) > 1:
        text = open(sys.argv[1], encoding="utf-8").read()
    else:
        text = sys.stdin.read()

    issues = lint(text)
    if not issues:
        print("PASS: no style violations")
        return 0
    print("FAIL:")
    for issue in issues:
        print(f"  - {issue}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
