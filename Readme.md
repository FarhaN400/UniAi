# 🎓 University Intelligent Question Answering System (UniAI)

> **An AI-powered university assistant that automatically collects official university notices, understands their contents, and answers student queries using Retrieval-Augmented Generation (RAG).**

🚧 **Project Status:** Active Development  
🎯 **Target:** Final Year B.Tech CSE Project  
🏫 **University:** Maulana Abul Kalam Azad University of Technology (MAKAUT)  
🤖 **Core Technologies:** Python • MongoDB Atlas • High-Res OCR • Pydantic • LangChain • Ollama (Qwen 3 4B-Instruct) • Pinecone Vector DB • Multi-Turn Conversational RAG  

---

## 📌 Overview

University students frequently struggle to find crucial information scattered across dozens of official circulars, examination notifications, admission notices, fee schedules, and academic updates published as unstructured PDFs.

**UniAI** solves this challenge by building an **intelligent, end-to-end university question-answering system** that automatically monitors university notice portals, converts raw PDF circulars into verified structured data, indexes them into a serverless vector database, and answers complex student queries conversationally with **zero hallucinations** and direct official citations.

Instead of requiring manual uploads or rigid keyword search, the system continuously ingests new notices and supports natural dialogue with conversational memory.

### 💡 Example Interactions

```text
Student: "What documents do I need for WBJEE 2026 admission reporting?"
UniAI:   "For WBJEE 2026 admission reporting at MAKAUT, you must submit:
          1. WBJEE 2026 Allotment Letter & Rank Card
          2. Class 10 & Class 12 Admit Cards & Marksheets
          3. Domicile Certificate and Category Certificate (if applicable)
          4. Anti-ragging declarations and medical fitness certificate.

          Source: https://makautwb.ac.in/datas/users/0-wbjee_reporting_2026.pdf"

Student: "Give me 3 latest notices"
UniAI:   [Returns 3 newest notices formatted with dates, summaries, and official links]

Student: "Now the second one"
UniAI:   [Expands specifically on the second notice from the previous list]

Student: "Which of these two hostel deadlines comes first, and by how many days?"
UniAI:   [Compares both notices, computes the exact date difference, and cites both sources]
```

---

# 🚀 Key Features

* 🔄 **Automated Portal Monitoring:** Continuously scans the MAKAUT notice board and detects newly published circulars without manual intervention.
* 🔐 **Cryptographic Deduplication:** Generates deterministic SHA-256 identifiers to guarantee idempotency and avoid duplicate database records.
* 📄 **Automated PDF Acquisition:** Streams notice PDFs to temporary storage and validates magic bytes (`%PDF-`) with automated cleanup.
* 🔍 **Enhanced High-Resolution OCR:** 300 DPI image rendering, contrast enhancement, layout segmentation, logo crest trimming, and font slant correction (`JJ` $\rightarrow$ `11 a.m.`).
* 📐 **Strict Pydantic Validation:** Formats unstructured notices into 10 structured dimensions (`ConfigDict(extra="forbid")`) with custom field validators.
* 🧩 **Intelligent Long-Document Chunking:** Segments long circulars (> 7,000 characters) along paragraph boundaries and merges chunk extractions deterministically.
* 🗄️ **Document Lifecycle Management:** Distinguishes `new`, `processed`, `review_required`, and `invalid` documents in MongoDB.
* 🔢 **Pinecone Vector Knowledge Base:** Synthesizes structured fields (including fees, dates, and action items) into integrated serverless embeddings tagged with 4-digit academic years.
* 🧠 **Query Understanding Layer:** Classifies user intent across 9 distinct categories, resolves temporal constraints, detects topic switches, and remembers student names.
* 💬 **Multi-Turn Conversational Memory:** Maintains session state, active notice focus, ordinal selections (*"3rd one"*), and exact citation tracking for multi-document comparisons.
* 🛡️ **Anti-Hallucination Prompting:** Enforces strict evidence grounding, fallback phrasing when context is absent, and mandatory official PDF citations.

---

# 🏗️ System Architecture

```text
                     ┌──────────────────────────┐
                     │     University Portal    │
                     │  (makautwb.ac.in/p=340)  │
                     └────────────┬─────────────┘
                                  │
                                  ▼
                     ┌──────────────────────────┐
                     │     MODULE 1             │
                     │  Automatic Web Scraper   │
                     │  SHA-256 Hashing         │
                     └────────────┬─────────────┘
                                  │
                                  ▼
                     ┌──────────────────────────┐
                     │        MongoDB           │
                     │  (status: "new")         │
                     └────────────┬─────────────┘
                                  │
                                  ▼
                     ┌──────────────────────────┐
                     │     MODULE 2             │
                     │  Document Processing     │
                     │  - PDF Download & Check  │
                     │  - High-Res OCR (300 DPI)│
                     │  - Qwen 3 4B via Ollama  │
                     │  - Pydantic Schema Check │
                     │  - Chunking & Merging    │
                     └────────────┬─────────────┘
                                  │
                                  ▼
                     ┌──────────────────────────┐
                     │        MongoDB           │
                     │  (status: "processed")   │
                     └────────────┬─────────────┘
                                  │
                                  ▼
                     ┌──────────────────────────┐
                     │     MODULE 3             │
                     │  Pinecone Vector Base    │
                     │  - Retrieval Text Build  │
                     │  - Year Tagging (20xx)   │
                     │  - Serverless Upsert     │
                     └────────────┬─────────────┘
                                  │
                                  ▼
                     ┌──────────────────────────┐
                     │     MODULE 4             │
                     │  Conversational RAG      │
                     │  - Query Understanding   │
                     │  - Conversational State  │
                     │  - Dual-Path Retrieval   │
                     │  - Anti-Hallucination RAG│
                     └────────────┬─────────────┘
                                  │
                                  ▼
                     ┌──────────────────────────┐
                     │     MODULE 5 (Planned)   │
                     │  Custom GPT Transformer  │
                     │  Built From Scratch      │
                     └────────────┬─────────────┘
                                  │
                                  ▼
                     ┌──────────────────────────┐
                     │     MODULE 6 (Planned)   │
                     │  Web Application & API   │
                     │  FastAPI + Interactive UI│
                     └──────────────────────────┘
```

---

# 🧩 Project Modules

---

## 1️⃣ Module 1 — Automatic University Notice Collection

### 🎯 Objective
Continuously monitors the official university notices page, detects newly published notices without manual document uploads, generates unique cryptographic identifiers, and persists them into MongoDB.

### Workflow
1. Fetches MAKAUT notice portal (`https://makautwb.ac.in/page.php?id=340`) using HTTP GET with timeout protection.
2. Identifies circular links (`a.text-danger[href]`) and normalizes relative URLs via `urllib.parse.urljoin`.
3. Detects "NEW" badge gifs (`images/new-08-june.gif`) to flag new notices on the portal.
4. Generates a deterministic SHA-256 identifier (`notice_id`) from the normalized URL.
5. Performs idempotent MongoDB upserts using `$setOnInsert` and unique index constraints, ensuring repeat executions never duplicate records or overwrite timestamps.
6. Flags known corrupt/broken links as `status: "invalid"`.

---

## 2️⃣ Module 2 — Document Processing & Structured Information Extraction

### 🎯 Objective
Transforms raw notice URLs into clean, structured JSON intelligence through automated PDF acquisition, high-resolution OCR preprocessing, Pydantic schema validation, and local LLM extraction.

### Workflow
1. **Acquisition & Verification:** Downloads notice PDFs to temporary storage and validates magic bytes (`%PDF-`). Non-PDF files raise `InvalidPDFError` and are flagged `status: "invalid"`.
2. **High-Res OCR (`ocr.py`):** Converts PDF pages at 300 DPI, applies grayscale filtering and 1.5x contrast enhancement, and executes Tesseract OCR with `--oem 3 --psm 6`.
3. **OCR Cleaning:** Normalizes line endings, fixes OCR slanted-font errors (`JJ a.m.` $\rightarrow$ `11 a.m.`), corrects date spacing glitches (`01.1 0.2026` $\rightarrow$ `01.10.2026`), and strips university crest logo noise.
4. **Pydantic Validation (`schema.py`):** Validates extraction outputs using `NoticeSchema` (`ConfigDict(extra="forbid")`), enforcing 10 core dimensions: notice type, title, reference number, issue date, target audience, important dates, fees, required actions, key points, and issuing authority.
5. **Long Notice Handling:** Circulars exceeding 7,000 characters are chunked into 2,500-character segments along paragraph boundaries, extracted individually, and merged deterministically with `merge_chunk_results`. Conflicting dates and fees are recorded for human review.
6. **Status Lifecycle:** Short notices are saved as `status: "processed"`, long notices as `status: "review_required"`, and temporary PDF files are guaranteed deleted in `finally:` blocks.

---

## 3️⃣ Module 3 — Knowledge Base & Pinecone Vector Storage

### 🎯 Objective
Converts processed university notices from MongoDB into an integrated vector knowledge base in Pinecone, preparing rich retrieval texts and indexing them with academic year metadata.

### Workflow
1. **Quality Filter:** Queries MongoDB notices with `status: "processed"` while excluding those requiring human quality review (`quality_review_required != True`).
2. **Retrieval Text Synthesis (`build_retrieval_text`):** Aggregates notice title, type, summary, action items, all key points, start/last dates, and fee amounts into a structured, newline-separated text representation.
3. **Year Extraction:** Extracts 4-digit academic/calendar years via regex from `issue_date` or title (e.g. `2025`, `2026`), tagging records with numeric `year` metadata.
4. **Pinecone Serverless Upsert:** Upserts records into the `uniai` index under the `notices` namespace using Pinecone's integrated embeddings (`index.upsert_records`).
5. **Synchronization:** Updates MongoDB documents with `pinecone_indexed: True` and UTC timestamp. Repeated runs skip already-indexed notices unless `reindex=True`.
6. **Search Verification (`search.py`):** Provides a standalone utility to test semantic search with title deduplication and similarity scores.

---

## 4️⃣ Module 4 — Conversational RAG & Multi-Turn Student Assistant

### 🎯 Objective
Provides students with an interactive, context-aware AI assistant capable of answering complex university queries, maintaining multi-turn dialogue, performing hybrid retrieval, and strictly grounding all responses in official circulars.

### Workflow
1. **Conversational Memory (`conversation_state.py`):**
   - Manages recent dialogue history within a sliding window.
   - Tracks the `active_notice` in discussion, clearing it when lists are returned.
   - Preserves `last_answer_records` (only notices explicitly cited in the previous answer) to enable precise multi-notice comparisons.
   - Memorizes student identity and name corrections (*"My name is Farhan"*, *"Correct my name to Farhan"*).
2. **Query Understanding Layer (`query_understanding.py`):**
   - Employs `qwen3:4b-instruct` (with deterministic fallback heuristics) to classify student messages into 9 intent classes: `casual_chat`, `latest_notices`, `today_notices`, `yesterday_notices`, `notice_search`, `topic_search`, `notice_followup`, `ordinal_followup`, and `multi_notice_followup`.
   - Detects topic switches (`explicitly_changes_notice_topic`) to break out of active notices when students change subjects.
3. **Dual-Path Hybrid Retrieval (`retrieve.py`):**
   - **Temporal Retrieval:** Queries MongoDB directly for latest notices or exact dates (*"today"*, *"yesterday"*), sorting by official issue date.
   - **Semantic Vector Search:** Queries Pinecone with year metadata filters (`{"year": {"$eq": year}}`), automatically falling back to filterless search with content verification if metadata is missing.
   - **Lexical Reranker:** Scores token overlap between query terms and notice text to break ties and differentiate document verification from registration closure circulars.
   - **Legacy Fallback:** Targeted regex search ensures older circulars not yet vectorized are never lost.
4. **Anti-Hallucination Prompting (`prompt.py` & `main.py`):**
   - System prompt strictly restricts answers to retrieved context.
   - Missing information triggers exact fallback: *"I could not find this information in the available university notices."*
   - Returns single-line listings for multi-notice queries and includes official PDF source URLs.
   - CLI interface allows interactive student questioning.

---

## 5️⃣ Module 5 — Custom GPT Architecture (Built From Scratch) [Planned]

### 🎯 Objective
Transition from pretrained open-weights models to a custom causal transformer built from scratch following Sebastian Raschka's *Build a Large Language Model (From Scratch)*.

### Planned Architecture:
- Custom Byte Pair Encoding (BPE) tokenizer trained on MAKAUT academic notices.
- Multi-Head Causal Self-Attention with Rotary Positional Embeddings (RoPE).
- Stacked Transformer blocks with LayerNorm and SwiGLU feed-forward networks.
- Domain pretraining and fine-tuning specifically tailored to university administrative Q&A.

---

## 6️⃣ Module 6 — User Interface & Application Deployment [Planned]

### 🎯 Objective
Deliver a responsive web and mobile application for students and faculty.

### Planned Features:
- Conversational chat UI with typing indicators and markdown rendering.
- Official Notice Cards with direct links and verified download previews.
- Deadlines & Important Dates Widget highlighting upcoming exams and admissions.
- Asynchronous FastAPI backend providing `/chat`, `/search`, and `/health` REST endpoints.

---

# 🛠️ Complete Technology Stack

| Layer | Technology | Purpose |
|---|---|---|
| **Programming Language** | Python 3.10+ | Core language across all modules |
| **Web Scraping** | Requests, BeautifulSoup4 | Portal crawling, HTML parsing, URL resolution |
| **Document Identification** | SHA-256 (`hashlib`) | Cryptographic notice deduplication |
| **Document Database** | MongoDB Atlas / PyMongo | Metadata, OCR raw text, and structured storage |
| **PDF Processing & OCR** | `pdf2image`, `pytesseract`, Pillow | 300 DPI conversion, contrast enhancement, text extraction |
| **Data Validation** | Pydantic V2 (`schema.py`) | Strict JSON contracts with forbidden extra fields |
| **Local LLM Engine** | Ollama | Local inference on Apple Silicon |
| **Language Model** | Qwen 3 4B-Instruct (`qwen3:4b-instruct`) | Structured extraction, intent classification, and RAG answering |
| **Vector Database** | Pinecone Serverless (`uniai` / `notices`) | Vector knowledge base with integrated embeddings |
| **Prompt Orchestration** | LangChain Core | Chains, prompt templates, and output parsers |
| **Reranking** | Lexical overlap reranker | Token matching for document vs registration distinction |
| **Configuration** | `python-dotenv` | Secure environment variable handling |

---

# 🗂️ Project Repository Structure

```text
UniAi/
│
├── Module1/
│   ├── scrapper.py               # Automated MAKAUT notice scraper & MongoDB upsert
│   ├── module1-revision-notes.md # Revision notes & portal DOM analysis
│   └── README.md                 # Module 1 documentation
│
├── Module2/
│   ├── main.py                   # PDF downloader, chunking engine, merger & batch processor
│   ├── ocr.py                    # 300 DPI OCR extraction, contrast enhancement & regex normalization
│   ├── schema.py                 # Pydantic validation models (NoticeSchema, ImportantDates, Fees)
│   ├── prompt.py                 # LLM extraction prompt & JSON output parser
│   └── README.md                 # Module 2 documentation
│
├── Module3/
│   ├── main.py                   # Retrieval text compiler & Pinecone serverless vector indexer
│   ├── search.py                 # Semantic search verification utility with title deduplication
│   └── Readme.md                 # Module 3 documentation
│
├── Module4/
│   ├── main.py                   # UniAI orchestrator, conversational CLI & response formatter
│   ├── retrieve.py               # Dual-path retrieval router (Pinecone semantic + MongoDB temporal)
│   ├── query_understanding.py    # Intent classifier (9 types), topic switcher & heuristic parser
│   ├── conversation_state.py     # Multi-turn memory, active notice tracking & name memorization
│   ├── prompt.py                 # Anti-hallucination LangChain RAG prompt template
│   ├── README_FIXES.md           # Patch notes on query classification & fallback logic
│   └── README.md                 # Module 4 documentation
│
├── Model/
│   └── test_ollama.py            # Local Ollama connection verification
│
├── .env                          # Local credentials (ignored by git)
├── .gitignore                    # Environment & artifact exclusions
├── requirement.txt               # Pinned Python package dependencies
└── Readme.md                     # Root project documentation
```

---

# 📊 Project Development Status

```text
Module 1  ████████████████████  100% ✅ (Automatic Web Scraper & Portal Monitor)
Module 2  ████████████████████  100% ✅ (Enhanced OCR, Pydantic Schema & Chunking)
Module 3  ████████████████████  100% ✅ (Knowledge Base & Pinecone Vector Store)
Module 4  ████████████████████  100% ✅ (Conversational State, Intent Parser & Hybrid RAG)
Module 5  ░░░░░░░░░░░░░░░░░░░░    0% 🔜 (Custom GPT Transformer Architecture from Scratch)
Module 6  ░░░░░░░░░░░░░░░░░░░░    0% 🔜 (Web Application UI & FastAPI REST Backend)
```

---

# ⚙️ Quick Start Guide

### 1. Environment Setup

Create a `.env` file in the project root:

```env
MONGO_URI=mongodb+srv://<username>:<password>@cluster0.mongodb.net/?retryWrites=true&w=majority
PINECONE_API_KEY=pcsk_...
```

### 2. Pull Local Model (Ollama)

```bash
ollama run qwen3:4b-instruct
```

### 3. Run Pipeline Modules

```bash
# Step 1: Scrape new notices from MAKAUT portal
cd Module1 && python3 scrapper.py

# Step 2: Download PDFs, run OCR, and extract structured data
cd ../Module2 && python3 main.py

# Step 3: Build retrieval representations and index into Pinecone
cd ../Module3 && python3 main.py

# Step 4: Start the Interactive UniAI Assistant
cd ../Module4 && python3 main.py
```

### 4. Debug Mode for Module 4

```bash
UNIAI_DEBUG=1 python3 main.py
```

---

## 👨‍💻 Author

**Farhan Akhtar**  
B.Tech — Computer Science & Engineering  
Maulana Abul Kalam Azad University of Technology (MAKAUT)  

---

> 🚀 **Building an AI system that doesn't just guess — it retrieves, grounds, and reasons over official university records with verified citations.**
