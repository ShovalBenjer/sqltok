#!/usr/bin/env python3
"""Generate a tiny BIRD-format fixture for the no-API smoke run.

This is NOT the BIRD dataset -- it is a couple of toy SQLite databases plus a
handful of questions in BIRD's JSON shape, committed so that
``run_bird.py --provider mock --data-dir benchmarks/sample_data`` works out of
the box. Re-run this script to regenerate the fixture.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAMPLE = HERE / "sample_data"
DB_ROOT = SAMPLE / "dev_databases"

RETAIL_DDL = """
CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, country TEXT);
CREATE TABLE orders (
  id INTEGER PRIMARY KEY, customer_id INTEGER, amount REAL, order_date TEXT,
  FOREIGN KEY (customer_id) REFERENCES customers(id)
);
CREATE TABLE line_items (
  id INTEGER PRIMARY KEY, order_id INTEGER, product_id INTEGER, qty INTEGER,
  FOREIGN KEY (order_id) REFERENCES orders(id),
  FOREIGN KEY (product_id) REFERENCES products(id)
);
CREATE TABLE products (id INTEGER PRIMARY KEY, sku TEXT, price REAL, category TEXT);
CREATE TABLE suppliers (id INTEGER PRIMARY KEY, company TEXT, nation TEXT);
"""

RETAIL_ROWS = """
INSERT INTO customers VALUES (1,'Acme','France'),(2,'Globex','Germany'),(3,'Initech','France');
INSERT INTO orders VALUES (1,1,99.5,'2026-01-05'),(2,2,150.0,'2026-02-01'),(3,1,42.0,'2026-02-15');
INSERT INTO products VALUES (1,'SKU-1',9.99,'widgets'),(2,'SKU-2',19.99,'gadgets');
INSERT INTO line_items VALUES (1,1,1,3),(2,1,2,1),(3,2,1,5);
INSERT INTO suppliers VALUES (1,'Globe Supply','USA'),(2,'EuroParts','Germany');
"""

SCHOOL_DDL = """
CREATE TABLE schools (id INTEGER PRIMARY KEY, name TEXT, district TEXT, county TEXT);
CREATE TABLE students (
  id INTEGER PRIMARY KEY, school_id INTEGER, grade INTEGER, score REAL,
  FOREIGN KEY (school_id) REFERENCES schools(id)
);
"""

SCHOOL_ROWS = """
INSERT INTO schools VALUES (1,'Maple High','North','Alameda'),(2,'Oak Elementary','South','Fresno');
INSERT INTO students VALUES (1,1,11,88.5),(2,1,12,91.0),(3,2,5,75.0);
"""

QUESTIONS = [
    {"question_id": 0, "db_id": "retail", "evidence": "revenue refers to SUM(amount)",
     "question": "What is the total order amount for customers in France?",
     "SQL": "SELECT SUM(o.amount) FROM orders o JOIN customers c ON o.customer_id=c.id WHERE c.country='France'"},
    {"question_id": 1, "db_id": "retail", "evidence": "",
     "question": "How many widgets were ordered in total?",
     "SQL": "SELECT SUM(li.qty) FROM line_items li JOIN products p ON li.product_id=p.id WHERE p.category='widgets'"},
    {"question_id": 2, "db_id": "retail", "evidence": "",
     "question": "List the company names of suppliers from Germany.",
     "SQL": "SELECT company FROM suppliers WHERE nation='Germany'"},
    {"question_id": 3, "db_id": "school", "evidence": "",
     "question": "What is the average score of students in Maple High?",
     "SQL": "SELECT AVG(s.score) FROM students s JOIN schools sc ON s.school_id=sc.id WHERE sc.name='Maple High'"},
    {"question_id": 4, "db_id": "school", "evidence": "",
     "question": "How many schools are in Alameda county?",
     "SQL": "SELECT COUNT(*) FROM schools WHERE county='Alameda'"},
]


def _write_db(db_id: str, ddl: str, rows: str) -> None:
    folder = DB_ROOT / db_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{db_id}.sqlite"
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.executescript(ddl)
    conn.executescript(rows)
    conn.commit()
    conn.close()


def main() -> None:
    SAMPLE.mkdir(parents=True, exist_ok=True)
    _write_db("retail", RETAIL_DDL, RETAIL_ROWS)
    _write_db("school", SCHOOL_DDL, SCHOOL_ROWS)
    (SAMPLE / "questions.json").write_text(json.dumps(QUESTIONS, indent=2))
    print(f"Wrote sample fixture to {SAMPLE}")


if __name__ == "__main__":
    main()
