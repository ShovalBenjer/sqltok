---
title: SQLTok
emoji: 🧮
colorFrom: indigo
colorTo: blue
sdk: streamlit
app_file: app.py
pinned: false
license: mit
---

# SQLTok live demo

Paste a schema and a question, pick a token budget, and watch SQLTok send the
LLM only the tables the question needs while keeping the selection
join-connected. Deterministic, no API keys.

## Deploy (2 minutes, pick one)

**Streamlit Community Cloud** (simplest, free):
1. share.streamlit.io -> New app -> pick `ShovalBenjer/sqltok`.
2. Set the main file path to `demo/app.py`.
3. Deploy. Public URL in ~2 minutes.

**Hugging Face Spaces**:
1. huggingface.co/new-space -> SDK: Streamlit.
2. Upload `app.py`, `requirements.txt`, and this `README.md` (it carries the
   Space config header).
3. The Space builds and serves automatically.

Both install `sqltok` straight from this repo (see `requirements.txt`).
