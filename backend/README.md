# ⚙️ UniAI Backend — Architecture & Services

> **University AI Assistant (UniAI) — MAKAUT**  
> High-performance Python backend powering automated notice ingestion, OCR extraction, Pinecone vector search, multi-turn conversational RAG, and isolated session management.

---

## 🏗️ Architecture Overview

The UniAI backend coordinates the complete pipeline from university portal monitoring to real-time conversational serving:

```text
backend/
├── app.py                    # FastAPI gateway (/api/chat, /health, CORS, session TTL)
├── retrieve.py               # Dual-path retrieval (Pinecone vector + MongoDB chronological)
│
├── Module1/                  # Web Scraper & Portal Monitor
│   ├── scrapper.py           # MAKAUT crawler, SHA-256 deduplication & PDF hash monitor
│   └── README.md             # Module 1 documentation
│
├── Module2/                  # Document Processing & Structured Extraction
│   ├── main.py               # Batch processor, PDF downloader, chunker & lease manager
│   ├── ocr.py                # Dual extraction (PyPDF direct + 300 DPI Tesseract OCR fallback)
│   ├── schema.py             # Pydantic V2 validation models (NoticeSchema)
│   ├── prompt.py             # Structured extraction prompt & JSON output parser
│   └── README.md             # Module 2 documentation
│
├── Module3/                  # Knowledge Base & Pinecone Vector Store
│   ├── main.py               # Pinecone serverless vector upsert (integrated embeddings)
│   ├── search.py             # Semantic search verification CLI utility
│   └── Readme.md             # Module 3 documentation
│
├── Module4/                  # Conversational RAG & Student Assistant
│   ├── main.py               # Assistant orchestrator & interactive CLI
│   ├── conversation_state.py # Multi-turn memory, active notice & user identity tracking
│   ├── query_understanding.py# 9-intent classifier & topic-switch detection
│   ├── evidence.py           # Server-side claim validation & anti-hallucination checks
│   ├── prompt.py             # LangChain anti-hallucination generation prompt
│   ├── README.md             # Module 4 documentation
│   └── README_FIXES.md       # Engineering changelog & reliability hardening
│
├── scheduler/                # Automated Notice Synchronization (Phase 5)
│   ├── sync_notices.py       # One-shot batch pipeline orchestrator
│   ├── run_with_atlas_access.py # Temporary Atlas IP authorization wrapper
│   ├── backfill_pdf_hashes.py # PDF checksum backfiller for legacy records
│   ├── report_pdf_baselines.py # PDF audit and OCR quality baseline reporter
│   ├── phase5_isolated_e2e_test.py # Ephemeral end-to-end integration test
│   └── README.md             # Scheduler & Phase 5 documentation
│
├── tests/                    # Regression test suites
├── test_phase5.py            # Complete offline unit & pipeline test suite (12/12 passing)
└── requirements-phase5.txt   # Lean dependencies for cloud CI/CD
```

---

## 🚀 Quick Start

### 1. Configure `.env` in Project Root

```env
MONGO_URI=mongodb+srv://<username>:<password>@cluster0.mongodb.net/?retryWrites=true&w=majority
PINECONE_API_KEY=pcsk_...

# LLM Provider: "groq" (cloud) or "ollama" (local)
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile
```

### 2. Run the FastAPI REST Server

```bash
cd backend
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

- **Interactive API Docs:** `http://127.0.0.1:8000/docs`
- **Health Check:** `http://127.0.0.1:8000/health`

### 3. Run Pipeline Modules Manually

```bash
# 1. Scrape latest notices
python3 backend/Module1/scrapper.py

# 2. Extract structured data via OCR + LLM
python3 backend/Module2/main.py

# 3. Index processed notices into Pinecone
python3 backend/Module3/main.py

# 4. Interactive CLI Assistant
python3 backend/Module4/main.py
```

### 4. Run Test Suites

```bash
python3 backend/test_phase5.py
```
