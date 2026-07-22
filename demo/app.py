# SQLTok live demo — paste a schema + a question, watch the token budget work.
# Runs on Hugging Face Spaces / Streamlit Cloud. Deterministic, no API keys.
import streamlit as st

from sqltok import SchemaBudgetManager

st.set_page_config(page_title="SQLTok", page_icon="🧮", layout="wide")

DEFAULT_DDL = """CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, city_id INTEGER, created_at TEXT);
CREATE TABLE cities (id INTEGER PRIMARY KEY, name TEXT, country_id INTEGER);
CREATE TABLE countries (id INTEGER PRIMARY KEY, name TEXT, region TEXT);
CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER, total REAL, status TEXT, placed_at TEXT,
                     FOREIGN KEY (customer_id) REFERENCES customers(id));
CREATE TABLE order_items (id INTEGER PRIMARY KEY, order_id INTEGER, product_id INTEGER, qty INTEGER,
                          FOREIGN KEY (order_id) REFERENCES orders(id), FOREIGN KEY (product_id) REFERENCES products(id));
CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, category_id INTEGER, price REAL);
CREATE TABLE categories (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE suppliers (id INTEGER PRIMARY KEY, name TEXT, country_id INTEGER);
CREATE TABLE inventory (product_id INTEGER, warehouse_id INTEGER, on_hand INTEGER);
CREATE TABLE warehouses (id INTEGER PRIMARY KEY, name TEXT, city_id INTEGER);
CREATE TABLE reviews (id INTEGER PRIMARY KEY, product_id INTEGER, customer_id INTEGER, stars INTEGER, body TEXT);
CREATE TABLE support_tickets (id INTEGER PRIMARY KEY, customer_id INTEGER, subject TEXT, status TEXT);"""

st.title("SQLTok")
st.caption(
    "Schema token-budget manager for Text-to-SQL. It sends the LLM only the "
    "tables a question needs, under a hard token budget, and keeps the "
    "selection join-connected. On BIRD it keeps 97% of gold tables at 2,000 tokens."
)

left, right = st.columns([1, 1])
with left:
    ddl = st.text_area("Schema (CREATE TABLE DDL)", DEFAULT_DDL, height=320)
with right:
    question = st.text_input(
        "Question", "Which customers in Germany placed the largest orders last month?"
    )
    budget = st.slider("Token budget", 200, 4000, 800, step=100)
    fk_expand = st.checkbox("Keep selection join-connected (FK expand)", value=True)
    go = st.button("Select schema", type="primary")

if go:
    try:
        mgr = SchemaBudgetManager.from_ddl(ddl)
    except Exception as e:
        st.error(f"Could not parse the DDL: {e}")
        st.stop()

    full = mgr.full_schema_text(include_sample_rows=False)
    full_tokens = mgr.count_tokens(full)
    ctx = mgr.build_context(question, token_budget=budget, include_sample_rows=False, fk_expand=fk_expand)

    saved = full_tokens - ctx.token_count
    pct = (saved / full_tokens * 100) if full_tokens else 0
    c1, c2, c3 = st.columns(3)
    c1.metric("Full schema", f"{full_tokens} tok")
    c2.metric("SQLTok selection", f"{ctx.token_count} tok", f"-{pct:.0f}%")
    c3.metric("Tables kept", f"{len(ctx.tables)} / {full.count('CREATE TABLE')}")

    st.text(f"Selected tables: {', '.join(ctx.tables)}")
    if ctx.bridge_tables:
        st.text(f"Bridge tables added for joins: {', '.join(ctx.bridge_tables)}")
    st.code(ctx.text, language="sql")
    st.caption(f"Selector: {ctx.selector} · budget {ctx.budget} · every token measured with tiktoken.")
