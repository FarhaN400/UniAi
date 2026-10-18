# 🎓 University Intelligent Question Answering System (UniAI)

> **An end-to-end, full-stack AI academic companion that automatically collects official university notices, extracts structured intelligence, and delivers verified, conversational answers grounded in official circulars with clickable citations.**

🚧 **Project Status:** Active Development  
🎯 **Target:** Final Year B.Tech CSE Project  
🏫 **University:** Maulana Abul Kalam Azad University of Technology (MAKAUT)  
🤖 **Core Technologies:** Python • FastAPI • React 18 • Vite • Tailwind CSS • MongoDB Atlas • High-Res OCR • Pydantic V2 • LangChain • Ollama (Qwen 3 4B-Instruct) • Pinecone Vector DB  

---

## 📌 Overview

University students frequently struggle to find crucial information scattered across dozens of official circulars, examination notifications, admission schedules, fee updates, and academic notices published as unstructured PDFs.

**UniAI** solves this challenge by building an **intelligent, end-to-end university question-answering system**:
1. Continuously scans university portals to ingest raw PDF notices.
2. Extracts and validates structured data using high-resolution OCR, Pydantic schemas, and local LLM extraction.
3. Indexes notices into a serverless vector database (Pinecone) with academic year metadata.
4. Employs a multi-turn Conversational RAG pipeline that enforces strict evidence grounding with zero hallucinations.
5. Delivers a modern, responsive web application (React + Vite + Tailwind CSS) where all links, official documents, and citations are fully interactive and clickable.

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

## 🚀 Key Features

* 🔄 **Automated Portal Monitoring:** Continuously scans the MAKAUT notice portal and detects newly published circulars without manual document uploads.
* 🔐 **Cryptographic Deduplication:** Generates deterministic SHA-256 identifiers to guarantee idempotency and avoid duplicate database records.
* 📄 **Automated PDF Acquisition:** Streams notice PDFs to temporary storage and validates magic bytes (`%PDF-`) with automated cleanup.
* 🔍 **Enhanced High-Resolution OCR:** 300 DPI image rendering, contrast enhancement, layout segmentation, logo crest trimming, and font slant correction (`JJ` $\rightarrow$ `11 a.m.`).
* 📐 **Strict Pydantic Validation:** Formats unstructured notices into 10 structured dimensions (`ConfigDict(extra="forbid")`) with custom field validators.
* 🧩 **Intelligent Long-Document Chunking:** Segments long circulars (> 7,000 characters) along paragraph boundaries and merges chunk extractions deterministically.
* 🗄️ **Document Lifecycle Management:** Distinguishes `new`, `processed`, `review_required`, and `invalid` documents in MongoDB.
* 🔢 **Pinecone Vector Knowledge Base:** Synthesizes structured fields into integrated serverless embeddings tagged with 4-digit academic years.
* 🧠 **Query Understanding Layer:** Classifies user intent across 9 distinct categories, resolves temporal constraints, detects topic switches, and remembers student names.
* 💬 **Multi-Turn Conversational Memory:** Maintains session state, active notice focus, ordinal selections (*"3rd one"*), and exact citation tracking for multi-document comparisons.
* 🛡️ **Anti-Hallucination Prompting & Evidence Verification:** Enforces strict evidence grounding, fallback phrasing when context is absent, and mandatory official PDF citations.
* 🌐 **Interactive Web Application:** Modern React 18 UI featuring auto-linked URLs, direct PDF badges, real-time generation progress tracking, and verified sources drawer.

---

## 🏗️ System Architecture

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
                     │     MODULE 6             │
                     │  Full-Stack Application  │
                     │  - FastAPI REST Backend  │
                     │  - React 18 + Vite UI    │
                     │  - Interactive Links     │
                     └────────────┬─────────────┘
                                  │
                                  ▼
                     ┌──────────────────────────┐
                     │     MODULE 5 (Planned)   │
                     │  Custom GPT Transformer  │
                     │  Built From Scratch      │
                     └──────────────────────────┘
```

---

## 🧩 Project Modules

---

### 1️⃣ Module 1 — Automatic University Notice Collection
* **Objective:** Continuously monitors the official university notices page, detects newly published notices without manual document uploads, generates unique cryptographic identifiers, and persists them into MongoDB.
* **Key Components:**
  - Fetches MAKAUT notice portal (`https://makautwb.ac.in/page.php?id=340`).
  - Normalizes relative URLs with `urllib.parse.urljoin`.
  - Flags "NEW" circulars and assigns SHA-256 hashes (`notice_id`).
  - Idempotent upserts via MongoDB `$setOnInsert`.

---

### 2️⃣ Module 2 — Document Processing & Structured Information Extraction
* **Objective:** Transforms raw notice URLs into clean, structured JSON intelligence through automated PDF acquisition, high-resolution OCR preprocessing, Pydantic schema validation, and local LLM extraction.
* **Key Components:**
  - Validates `%PDF-` magic bytes; removes temporary files safely in `finally:` blocks.
  - Converts PDF pages at 300 DPI with contrast enhancement (`ocr.py`).
  - Formats extractions into 10 strict dimensions with Pydantic V2 (`NoticeSchema`).
  - Chunks circulars > 7,000 characters and merges extractions deterministically.

---

### 3️⃣ Module 3 — Knowledge Base & Pinecone Vector Storage
* **Objective:** Converts processed notices from MongoDB into an integrated serverless vector knowledge base in Pinecone with academic year metadata.
* **Key Components:**
  - Filters notices with `status: "processed"`.
  - Synthesizes retrieval texts incorporating titles, summaries, dates, and fees (`build_retrieval_text`).
  - Extracts 4-digit academic years via regex.
  - Upserts vectors into the `uniai` index under the `notices` namespace.

---

### 4️⃣ Module 4 — Conversational RAG & Multi-Turn Student Assistant
* **Objective:** Provides students with an interactive, context-aware AI assistant capable of answering complex university queries, maintaining multi-turn dialogue, and strictly grounding responses in official circulars.
* **Key Components:**
  - **Memory (`conversation_state.py`):** Multi-turn history, active notice focus, student name memorization.
  - **Query Understanding (`query_understanding.py`):** Intent classification across 9 types, topic-switch detection, and temporal parsing.
  - **Dual-Path Hybrid Retrieval (`retrieve.py`):** Pinecone dense semantic search + MongoDB temporal & keyword matching.
  - **Anti-Hallucination RAG (`prompt.py` & `evidence.py`):** Validates claims against explicit fact references, preventing fabricated dates or fee amounts.

---

### 5️⃣ Module 6 — Full-Stack Web Application & API
* **Objective:** Deliver a modern, high-performance web application connecting students to official notices through an intuitive interface with verified link clickability.
* **Key Components:**
  - **FastAPI REST API (`backend/app.py`):** `/api/chat`, `/health`, session store isolation, local network CORS.
  - **Interactive Link Engine (`FormattedMessage.jsx`):** Parses all raw URLs and Markdown links into styled, accessible links opening in new tabs. Distinguishes PDF circulars with document badges.
  - **Notice Documents Tray:** Quick-access chip strip under assistant messages listing all cited documents.
  - **Real-Time Generation Progress Tracker:** Elapsed seconds timer with stage-based progress indicators.
  - **Verified Sources Drawer:** Slide-over panel displaying cited circular titles, dates, and direct links.
  - **Quick Portals Directory:** Instant links in Settings and Sidebar to MAKAUT Official Website, Exam Portal, and Notice Board.

---

### 6️⃣ Module 5 — Custom GPT Architecture (Built From Scratch) [Planned]
* **Objective:** Transition from pretrained open-weights models to a custom causal transformer built from scratch following Sebastian Raschka's *Build a Large Language Model (From Scratch)*.
* **Planned Architecture:**
  - Custom Byte Pair Encoding (BPE) tokenizer trained on MAKAUT academic notices.
  - Multi-Head Causal Self-Attention with Rotary Positional Embeddings (RoPE).
  - Stacked Transformer blocks with LayerNorm and SwiGLU feed-forward networks.

---

## 🛠️ Complete Technology Stack

| Layer | Technology | Purpose |
|---|---|---|
| **Frontend Framework** | React 18, Vite | High-performance interactive user interface |
| **Styling & Icons** | Tailwind CSS, Lucide Icons | Responsive modern layout, dark mode, accessible icons |
| **Backend API** | FastAPI, Uvicorn | Asynchronous REST backend & session state management |
| **Programming Language** | Python 3.9+ | Core backend logic across all pipeline modules |
| **Web Scraping** | Requests, BeautifulSoup4 | Portal crawling, HTML parsing, URL resolution |
| **Document Identification** | SHA-256 (`hashlib`) | Cryptographic notice deduplication |
| **Document Database** | MongoDB Atlas / PyMongo | Metadata, OCR raw text, and structured storage |
| **PDF Processing & OCR** | `pdf2image`, `pytesseract`, Pillow | 300 DPI conversion, contrast enhancement, text extraction |
| **Data Validation** | Pydantic V2 | Strict JSON schema contracts |
| **Local LLM Engine** | Ollama | Local model execution with 30m GPU keep-alive |
| **Language Model** | Qwen 3 4B-Instruct (`qwen3:4b-instruct`) | Extraction, intent classification, and RAG answering |
| **Vector Database** | Pinecone Serverless (`uniai` / `notices`) | Vector knowledge base with integrated embeddings |
| **Prompt Orchestration** | LangChain Core | RAG prompts, claim parsers, and evidence chaining |

---

## 🗂️ Project Repository Structure

```text
UniAi/
├── backend/
│   ├── app.py                    # FastAPI entry point (/api/chat, /health, CORS)
│   ├── retrieve.py               # Hybrid retrieval router (Pinecone semantic + MongoDB temporal)
│   ├── Module1/
│   │   ├── scrapper.py           # Automated MAKAUT notice scraper & MongoDB upsert
│   │   └── README.md             # Module 1 documentation
│   ├── Module2/
│   │   ├── main.py               # PDF downloader, chunking engine & merger
│   │   ├── ocr.py                # 300 DPI OCR extraction & regex normalization
│   │   ├── schema.py             # Pydantic validation models (NoticeSchema)
│   │   ├── prompt.py             # Extraction prompt & output parser
│   │   └── README.md             # Module 2 documentation
│   ├── Module3/
│   │   ├── main.py               # Pinecone serverless vector indexer
│   │   ├── search.py             # Semantic search verification utility
│   │   └── Readme.md             # Module 3 documentation
│   ├── Module4/
│   │   ├── main.py               # Conversational orchestrator & response generator
│   │   ├── query_understanding.py# Intent classifier, topic switcher & heuristic parser
│   │   ├── conversation_state.py # Multi-turn memory & session tracking
│   │   ├── evidence.py           # Fact extraction, claim validation & source formatting
│   │   ├── prompt.py             # Anti-hallucination RAG prompt template
│   │   └── README.md             # Module 4 documentation
│   ├── Model/
│   │   └── test_ollama.py        # Ollama local connection verification
│   └── tests/                    # Regression and evidence validation test suites
│
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── Composer.jsx      # Chat input with send button & keyboard shortcuts
│   │   │   ├── FormattedMessage.jsx # Interactive URL linkifier, Markdown renderer & PDF detector
│   │   │   ├── Sidebar.jsx       # Navigation drawer, history list & official portal link
│   │   │   └── SourcePanel.jsx   # Slide-over official notice citations drawer
│   │   ├── lib/
│   │   │   ├── api.js            # FastAPI fetch client (180s timeout, URL normalization)
│   │   │   └── storage.js        # LocalStorage helpers for chat history & theme
│   │   ├── pages/
│   │   │   ├── Chat.jsx          # Chat stream, progress tracker & direct links tray
│   │   │   ├── History.jsx       # Conversation history management
│   │   │   ├── Home.jsx          # Welcome page with prompt starter cards
│   │   │   └── Settings.jsx      # Theme toggle & official university links directory
│   │   ├── App.jsx               # Application layout & state management
│   │   └── index.css             # Tailwind base & typography styles
│   ├── package.json              # Frontend dependencies and scripts
│   ├── vite.config.js            # Vite configuration
│   └── README.md                 # Frontend-specific documentation
│
├── .env                          # Local backend credentials (ignored by git)
├── .gitignore                    # Git exclusions
├── requirements.txt              # Python package dependencies
└── Readme.md                     # Root project documentation
```

---

## 📊 Project Development Status

```text
Module 1  ████████████████████  100% ✅ (Automatic Web Scraper & Portal Monitor)
Module 2  ████████████████████  100% ✅ (Enhanced OCR, Pydantic Schema & Chunking)
Module 3  ████████████████████  100% ✅ (Knowledge Base & Pinecone Vector Store)
Module 4  ████████████████████  100% ✅ (Conversational State, Intent Parser & Hybrid RAG)
Module 6  ████████████████████  100% ✅ (Full-Stack Web App: FastAPI + React UI + Interactive Links)
Module 5  ░░░░░░░░░░░░░░░░░░░░    0% 🔜 (Custom GPT Transformer Architecture from Scratch)
```

---

## ⚙️ Quick Start Guide

### 1. Environment Setup

Create a `.env` file in the project root:

```env
MONGO_URI=mongodb+srv://<username>:<password>@cluster0.mongodb.net/?retryWrites=true&w=majority
PINECONE_API_KEY=pcsk_...
OLLAMA_KEEP_ALIVE=30m
```

Create a `.env` file in the `frontend/` directory:

```env
VITE_API_BASE_URL=http://localhost:8000
```

---

### 2. Start Ollama Local Model

Ensure Ollama is installed and run the Qwen 3 model:

```bash
ollama run qwen3:4b-instruct
```

---

### 3. Start the FastAPI Backend

From the repository root, activate your Python virtual environment and launch `uvicorn`:

```bash
cd backend
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

The API will be available at:
- **API URL:** `http://127.0.0.1:8000`
- **Interactive Swagger Docs:** `http://127.0.0.1:8000/docs`
- **Health Check:** `http://127.0.0.1:8000/health`

---

### 4. Start the React Frontend

Open a new terminal tab and start the frontend:

```bash
cd frontend
npm install
npm run dev
```

Open your browser to:
- **Local Application:** `http://localhost:5173`
- **LAN Access:** `http://<your-ip>:5173` (supported via backend CORS regex)

---

### 5. Running the Pipeline Manually (Data Ingestion)

If you wish to scrape new circulars, re-OCR notices, or rebuild the vector index:

```bash
# Step 1: Scrape new notices from MAKAUT portal
python3 backend/Module1/scrapper.py

# Step 2: Download PDFs, run OCR, and extract structured data
python3 backend/Module2/main.py

# Step 3: Build retrieval representations and index into Pinecone
python3 backend/Module3/main.py

# Step 4: Run CLI Assistant (optional)
python3 backend/Module4/main.py
```

---

### 6. Running Test Suites

Run the claim validation and evidence grounding regression tests:

```bash
cd backend
python3 test_phase2.py
python3 test_phase2_eligibility.py
python3 test_phase2_missing_values.py
python3 test_phase2_overview_merge.py
python3 test_phase2_precision.py
```

---

## 👨‍💻 Author

**Farhan Akhtar**  
B.Tech — Computer Science & Engineering  
Maulana Abul Kalam Azad University of Technology (MAKAUT)  

---

> 🚀 **Building an AI system that doesn't just guess — it retrieves, grounds, and reasons over official university records with verified, clickable citations.**
