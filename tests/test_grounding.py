"""Tests for the native value-grounding layer (MinHash + LSH + mentions)."""

from __future__ import annotations

from sqltok import SchemaGrounding, parse_ddl
from sqltok.grounding import MinHasher, extract_mentions
from sqltok.grounding.text import char_shingles


def test_minhash_estimates_jaccard() -> None:
    hasher = MinHasher(num_perm=128, seed=1)
    a = char_shingles("United States")
    b = char_shingles("United States of America")
    c = char_shingles("France")
    sab = MinHasher.estimate_jaccard(hasher.signature(a), hasher.signature(b))
    sac = MinHasher.estimate_jaccard(hasher.signature(a), hasher.signature(c))
    assert sab > sac
    assert MinHasher.estimate_jaccard(hasher.signature(a), hasher.signature(a)) == 1.0


def test_minhash_is_deterministic() -> None:
    h1 = MinHasher(num_perm=64, seed=7)
    h2 = MinHasher(num_perm=64, seed=7)
    sh = char_shingles("widgets")
    assert (h1.signature(sh) == h2.signature(sh)).all()


def test_mention_extraction_trims_stopwords_and_keeps_phrases() -> None:
    mentions = extract_mentions("What was the total revenue by region")
    assert "total revenue" in mentions
    assert "region" in mentions
    # Pure stopwords are not emitted as standalone mentions.
    assert "the" not in mentions
    assert "was" not in mentions


def test_mention_extraction_keeps_quoted_literals() -> None:
    mentions = extract_mentions("customers in 'United States'")
    assert "United States" in mentions


def test_value_grounding_matches_cell_value_not_column_name() -> None:
    # 'widgets' is a VALUE in products.category, never a column or table name.
    ddl = """
    CREATE TABLE products (id INTEGER PRIMARY KEY, sku TEXT, category TEXT);
    CREATE TABLE staff (id INTEGER PRIMARY KEY, fullname TEXT);
    """
    schema = parse_ddl(ddl)
    schema.tables["products"].columns[2].sample_values = ["widgets", "gadgets"]
    grounding = SchemaGrounding(schema)
    gq = grounding.ground("how many widgets are there")
    pi = gq.table_order.index("products")
    si = gq.table_order.index("staff")
    # products is grounded via its cell value; staff is not.
    assert gq.cover[pi].max() > gq.cover[si].max()
    assert gq.cover[pi].max() > 0.5


def test_idf_weights_downweight_ubiquitous_mentions() -> None:
    ddl = """
    CREATE TABLE a (id INTEGER PRIMARY KEY, status TEXT);
    CREATE TABLE b (id INTEGER PRIMARY KEY, status TEXT);
    CREATE TABLE c (id INTEGER PRIMARY KEY, region TEXT);
    """
    schema = parse_ddl(ddl)
    grounding = SchemaGrounding(schema)
    gq = grounding.ground("status by region")
    if "status" in gq.mentions and "region" in gq.mentions:
        w_status = gq.weights[gq.mentions.index("status")]
        w_region = gq.weights[gq.mentions.index("region")]
        # 'region' hits one table, 'status' hits two -> region is more specific.
        assert w_region >= w_status
