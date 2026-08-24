# A Visual Guide to SQLTok

This guide has moved to the site. See the canonical, fully-rendered version with
diagrams and math typeset at:

> **[A Visual Guide to SQLTok — Submodular Schema Selection for Text-to-SQL](https://sqltok.dev/posts/visual-guide-to-sqltok/)**

The post covers the full pipeline: value grounding with MinHash and LSH,
submodular coverage selection, foreign-key Steiner connectivity, and the hard
token-budget guarantee. It also includes benchmark numbers on BIRD mini-dev and
the formal `(1 - 1/e)` guarantee with proofs.

For the in-repo implementation, see `sqltok/grounding/` and `sqltok/select/`.
