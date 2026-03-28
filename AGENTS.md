# AGENTS.md

## Project Overview

**Domain Finder** — An intelligent domain/website discovery tool in Python. It finds websites that ARE a specific type of business (e.g., real e-commerce stores) rather than websites that merely talk about that topic.

The `main` branch contains only a README. All code lives on 4 feature branches, each a self-contained variant of the same product:

| Branch | Variant | Framework | Port |
|---|---|---|---|
| `cursor/detecci-n-de-tipo-de-web-e6cc` | FastAPI REST API | FastAPI + Uvicorn | 8000 |
| `cursor/detecci-n-de-tipo-de-web-a853` | Flask Web UI + Gemini AI | Flask | 5000 |
| `cursor/detecci-n-de-tipo-de-web-7c36` | Minimal CLI pipeline | CLI only | N/A |
| `cursor/detecci-n-de-dominios-precisa-e313` | Streamlit + NLP/Embeddings | Streamlit | 8501 |

## Cursor Cloud specific instructions

### Branch Architecture

Each branch has its **own `requirements.txt`** with incompatible dependency sets. When working on a specific branch, use a dedicated virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Running Tests

All branches use `pytest`. Tests are in `tests/` at the repo root. No API keys are needed for unit tests.

```bash
python -m pytest tests/ -v
```

### Running Linting

```bash
pip install ruff
ruff check .
```

Pre-existing style issues exist (26 auto-fixable with `ruff check --fix`); these are not blockers.

### Starting Development Servers

Each branch has a different startup command:

- **e6cc (FastAPI):** `python main.py --serve` (port 8000) — Swagger docs at `/docs`
- **a853 (Flask):** `python run_web.py` (port 5000)
- **7c36 (CLI):** `python src/main.py "your prompt"` — no server, CLI only
- **e313 (Streamlit):** `streamlit run app.py` (port 8501)

All servers require `SERPER_API_KEY` env var for actual search functionality. You can start servers with a dummy key (`SERPER_API_KEY=test`) to verify the server boots and endpoints respond (health checks, metadata endpoints work without a real key).

### External API Dependencies

- **SERPER_API_KEY** (required for search): Get from https://serper.dev
- **GEMINI_API_KEY** (optional, a853 branch only): For AI prompt interpretation
- **PAGESPEED_API_KEY** (optional): For PageSpeed Insights metrics

### Key Gotchas

- The e313 branch requires `sentence-transformers` and `fasttext-wheel` which are heavy ML dependencies (~2GB); install may take several minutes.
- The a853 branch uses `playwright` for contact extraction; run `playwright install chromium` after pip install if needed.
- The `python3.12-venv` system package must be installed before creating virtual environments (`sudo apt-get install python3.12-venv`).
