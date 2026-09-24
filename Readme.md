# 🎓 University Intelligent Question Answering System

> **An AI-powered university assistant that automatically collects official university notices, understands their contents, and answers student queries using Retrieval-Augmented Generation (RAG).**

🚧 **Project Status:** In Development
🎯 **Target:** Final Year B.Tech CSE Project
🏫 **University:** MAKAUT
🤖 **Core Technologies:** Python • MongoDB • OCR • LangChain • LLM • Embeddings • Vector Database • RAG

---

## 📌 Overview

University students often have to search through multiple notices, PDFs, circulars, scholarship announcements, examination notifications, and academic updates to find a single piece of information.

This project aims to solve that problem by building an **intelligent university question-answering system** that automatically collects official university documents and makes their information searchable through natural-language questions.

Instead of manually uploading documents, the system continuously monitors the university website and automatically processes newly published notices.

### 💡 Example

A student can ask:

> **"What is the last date for examination form submission?"**

Instead of searching through dozens of PDFs, the system will:

```text
Student Question
       ↓
Query Processing
       ↓
Vector Search
       ↓
Relevant University Notice
       ↓
LLM
       ↓
Accurate Answer
       ↓
Source / Notice Reference
```

---

# 🚀 Key Features

* 🔄 **Automatic University Notice Monitoring**
* 🌐 Scrapes official university notices directly from the website
* 📄 Automatically downloads newly detected PDF documents
* 🔍 OCR-based text extraction from PDF documents
* 🧠 LLM-powered information extraction
* 📦 Converts unstructured notices into structured JSON
* 🗄️ MongoDB-based document management
* 🧩 Intelligent document chunking
* 🔢 Embedding generation
* 🗃️ Vector database for semantic search
* 🔎 Retrieval-Augmented Generation (RAG)
* 💬 Natural-language question answering
* 📚 Source-aware answers based on university documents
* ⚡ Automatic processing of newly published notices
* 🧱 Modular architecture for future model replacement

---

# 🏗️ System Architecture

```text
                    ┌──────────────────────────┐
                    │     University Website   │
                    │      MAKAUT Portal       │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │     MODULE 1             │
                    │  Automatic Web Scraper   │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │        MongoDB           │
                    │ Notice Metadata + URL    │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │     MODULE 2             │
                    │  Document Processing     │
                    │                          │
                    │ PDF → OCR → Text → LLM  │
                    │        → Structured JSON │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │        MongoDB           │
                    │ Raw Text + Structured    │
                    │ JSON + Processing Status │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │     MODULE 3             │
                    │   Pinecone Vector Base   │
                    │                          │
                    │ Retrieval Text Build →   │
                    │ Vector Upsert + Tracking │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │     MODULE 4 (NEXT)      │
                    │  Student Query & RAG     │
                    │                          │
                    │ Student Query → Search → │
                    │ Context → LLM Response   │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │     MODULE 5             │
                    │   Custom GPT / LLM       │
                    │                          │
                    │ Transformer Architecture │
                    │ Built From Scratch       │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │     MODULE 6             │
                    │  User Interface & API    │
                    │  Web / Chat Application  │
                    └──────────────────────────┘
```

---

# 🧩 Project Modules

## 1️⃣ Module 1 — Automatic University Notice Collection

### 🎯 Objective

Automatically monitor the university website and detect newly published notices without requiring manual PDF uploads.

### Workflow

```text
MAKAUT Website
      ↓
Requests
      ↓
BeautifulSoup
      ↓
Extract Notice Title + URL
      ↓
Generate Unique Notice ID
      ↓
Check MongoDB
      ↓
New Notice?
   ↙       ↘
 YES       NO
  ↓         ↓
Store      Ignore
```

### Technologies

* Python
* Requests
* BeautifulSoup
* URL parsing
* SHA-256 hashing
* PyMongo
* MongoDB Atlas

### Notice Identification

Each notice receives a unique identifier generated from its URL:

```python
notice_id = hashlib.sha256(
    notice["url"].encode()
).hexdigest()
```

This prevents duplicate notices from being inserted.

### MongoDB Example

```json
{
  "notice_id": "...",
  "detected_at": "...",
  "flagged_new_on_site": true,
  "status": "new",
  "title": "University Notice",
  "url": "https://makautwb.ac.in/...pdf"
}
```

### Current Status

✅ Completed

The system has already been tested with a large collection of university notices.

---

# 2️⃣ Module 2 — Document Processing & Intelligent Information Extraction

### 🎯 Objective

Convert unstructured university PDF notices into useful, structured information automatically.

The system does **not require manually reading every PDF**.

### Workflow

```text
MongoDB
   ↓
Find status = "new"
   ↓
Get PDF URL
   ↓
Download PDF
   ↓
OCR
   ↓
Extract Text
   ↓
LLM
   ↓
Structured JSON
   ↓
Save to MongoDB
   ↓
status = "processed"
```

### Technologies

* Python
* Requests
* OCR
* LangChain
* Hugging Face
* GPT-OSS-120B
* Structured Output Parser
* MongoDB

### OCR Pipeline

University PDFs may contain scanned documents where normal PDF text extraction is insufficient.

Therefore, OCR is used to extract readable text:

```text
PDF
 ↓
OCR
 ↓
Text
```

### LLM Information Extraction

The extracted text is passed to the LLM.

The LLM identifies important information such as:

* Notice category
* Target audience
* Important dates
* Deadlines
* Fees
* Eligibility
* Required documents
* Required actions
* Instructions
* Summary

The output is converted into structured JSON.

### Example

```json
{
  "notice_type": "Examination",
  "target_students": "B.Tech Students",
  "important_dates": {
    "start_date": "2026-09-15",
    "last_date": "2026-09-25"
  },
  "fees": {
    "amount": 500,
    "currency": "INR"
  },
  "action_required": "Complete examination form submission",
  "summary": "..."
}
```

### MongoDB After Processing

```json
{
  "notice_id": "...",
  "title": "...",
  "url": "...",
  "status": "processed",

  "raw_text": "...",

  "structured_data": {
    "notice_type": "...",
    "important_dates": {},
    "action_required": "...",
    "summary": "..."
  },

  "processed_at": "..."
}
```

### Important Design

Downloaded PDFs are used for processing and are not intended to accumulate permanently on the local machine.

The important persistent information is:

```text
MongoDB
 ├── Notice Metadata
 ├── Raw OCR Text
 └── Structured JSON
```

### Current Status

✅ Completed

---

# 3️⃣ Module 3 — Knowledge Base & Pinecone Vector Storage

### 🎯 Objective

Convert the structured information generated in **Module 2** into a searchable vector knowledge base using **Pinecone**.

Instead of searching university notices through traditional keyword matching, the processed notices from MongoDB are converted into rich retrieval-friendly representations and indexed into Pinecone to enable semantic search based on the meaning of student queries.

### Workflow

```text
Processed Notices (MongoDB: status = "processed")
                       │
                       ▼
              Check Indexing Status
             (pinecone_indexed == True?)
               ↙                     ↘
             Yes                      No
              │                        │
              ▼                        ▼
            Skip             Build Retrieval Text
                             (Title, Type, Summary,
                             Key Points, Deadlines)
                                       │
                                       ▼
                             Pinecone Vector Index
                             (Namespace: "notices")
                                       │
                                       ▼
                               Update MongoDB
                          ("pinecone_indexed": True,
                           "pinecone_indexed_at")
                                       │
                                       ▼
                           Ready for Semantic Search
```

### Technologies

* Python
* Pinecone (`pinecone` SDK)
* PyMongo
* MongoDB Atlas
* python-dotenv
* `datetime` (UTC timestamps)

### Retrieval Text Construction

The structured data stored in MongoDB during Module 2 is transformed into a unified text representation optimized for semantic embedding and retrieval:

* **Notice Title:** Primary context
* **Notice Type:** Category (e.g., Examination, Admission, Scholarship)
* **Summary:** High-level overview of the notice
* **Key Points:** Bullet points extracted by LLM
* **Important Dates / Deadlines:** Critical timing information

```python
def build_retrieval_text(notice):
    sd = notice["structured_data"]
    parts = [
        sd.get("title", ""),
        sd.get("notice_type", ""),
        sd.get("summary", ""),
    ]
    key_points = sd.get("key_points", [])
    if key_points:
        parts.append(" ".join(key_points))
    deadline = sd.get("important_dates", {}).get("last_date")
    if deadline:
        parts.append(f"Deadline: {deadline}")
    return " ".join(p for p in parts if p)
```

### Pinecone Indexing & Record Schema

Each processed notice is upserted into the `notices` namespace of the Pinecone index (`uniai`):

```python
index.upsert_records(
    namespace="notices",
    records=[{
        "id": notice["notice_id"],
        "text": text,
        "title": notice["structured_data"].get("title"),
        "notice_type": notice["structured_data"].get("notice_type"),
        "url": notice["url"],
    }]
)
```

#### Record Structure:

| Field | Description |
| --- | --- |
| `id` | Unique SHA-256 notice identifier (`notice_id`) |
| `text` | Unified retrieval-friendly text |
| `title` | Notice title |
| `notice_type` | Category of the notice |
| `url` | Original MAKAUT notice URL |

### MongoDB Index Tracking & Duplicate Prevention

To prevent re-indexing notices on subsequent runs, MongoDB tracks the Pinecone indexing status:

```python
{
    "pinecone_indexed": True,
    "pinecone_indexed_at": datetime.now(timezone.utc)
}
```

* **Incremental Indexing (`reindex=False`):** Queries only notices with `"status": "processed"` where `pinecone_indexed` is missing or `False`.
* **Reindexing Support (`reindex=True`):** Allows a complete refresh of the Pinecone knowledge base.
* **Batch Processing:** Supports a `limit` parameter for testing and incremental batch upserts.

### Semantic Search Verification

The module includes semantic search verification (`search.py`) using Pinecone's `search_records` API:

```python
def search_notices(question, top_k=3):
    results = index.search_records(
        namespace="notices",
        query={
            "inputs": {"text": question},
            "top_k": top_k
        }
    )
```

Results are normalized and deduplicated by title to return the top most relevant notices and similarity scores for any student query.

### Current Status

✅ Completed

> [!NOTE]
> **Architecture & Scope Integration:**
> The vector database layer (initially planned as a separate Module 4) was consolidated directly into **Module 3** using Pinecone serverless indexing (`index.upsert_records`). This unified retrieval text preparation and vector storage into a single operational knowledge base, allowing the next phase to focus directly on **Student Query Processing & RAG**.

---

# 4️⃣ Module 4 — Student Query Processing, Semantic Retrieval & RAG Pipeline

### 🎯 Objective

Connect natural-language student questions to the official university knowledge base.

Instead of browsing dozens of PDF circulars or relying on brittle keyword matching, students can ask questions directly in natural language (e.g. *"What is the last date for submitting the examination form?"* or *"What documents do I need for WBJEE reporting?"*).

Module 4 will understand the student's intent, perform semantic vector search against the Pinecone `notices` namespace, retrieve the most relevant official university circulars, construct grounded context, and prompt the LLM to generate an accurate, verified answer citing the official MAKAUT notice and source URL.

### 🔄 Student Query & RAG Workflow

```text
Student Question
       │
       ▼
Query Preprocessing & Intent Recognition
       │
       ▼
Pinecone Semantic Search
(namespace: "notices", inputs: {"text": question}, top_k=3)
       │
       ▼
Relevance Ranking & Title Deduplication
       │
       ▼
Grounded Context Assembly
(Title, Type, Summary, Key Points, Deadlines, Source URL)
       │
       ▼
RAG Prompt Construction
       │
       ▼
LLM Generation
(Hugging Face: gpt-oss-120b)
       │
       ▼
Verified Answer + Direct Notice Citation & Link
```

### 💡 Example Interaction

```text
Student:
"What documents do I need for WBJEE 2026 admission reporting?"

        │
        ▼

Pinecone Semantic Retrieval:
- Found Notice: "Notification for reporting of candidates for admission through WBJEE-2026"
- Similarity Score: 0.892
- Official URL: https://makautwb.ac.in/notice_wbjee_2026.pdf

        │
        ▼

RAG Prompt Injected:
Context: [Title, Key Points: Allotment card, Rank card, Class 10/12 marksheet, Domicile certificate...]
Question: "What documents do I need for WBJEE 2026 admission reporting?"

        │
        ▼

AI Assistant Answer:
"For WBJEE 2026 admission reporting at MAKAUT, you must submit:
1. WBJEE 2026 Allotment Letter & Rank Card
2. Class 10 & Class 12 Admit Cards & Marksheets
3. Domicile Certificate and Category Certificate (if applicable)
4. Anti-ragging declarations and medical fitness certificate.

Source: Notification for reporting of candidates for admission through WBJEE-2026
URL: https://makautwb.ac.in/notice_wbjee_2026.pdf"
```

### Planned Components

* **Query Preprocessing (`query_processor.py`)**: Normalization, time/session keyword detection (e.g., "Phase 2", "2026", "JELET"), and intent classification.
* **Semantic Retriever (`retriever.py`)**: Calling Pinecone's `search_records`, title deduplication, relevance score filtering, and top-$K$ notice extraction.
* **RAG Prompt Chain (`rag_pipeline.py`)**: Assembling retrieved notice context with anti-hallucination system instructions.
* **Source Attribution & Grounding**: Appending official MAKAUT notice URLs, titles, and dates to every answer so students can verify information independently.

### Technologies

* Python
* Pinecone SDK (`search_records`)
* LangChain Core (Prompt Templates & Chains)
* Hugging Face Endpoint (`openai/gpt-oss-120b`)
* PyMongo (Metadata enrichment)

### Current Status

🔜 **Next Module (Up Next)**

---

# 5️⃣ Module 5 — Custom GPT Architecture (Built From Scratch)

### 🎯 Objective

Transition from a third-party pretrained LLM to a **custom GPT-style language model built from scratch**.

While Phase 1 uses a pretrained model (`gpt-oss-120b`) to build and validate the complete retrieval and QA pipeline, Phase 2 implements a custom causal transformer designed and trained specifically for university question answering.

The architecture follows the principles outlined in:
📖 *Build a Large Language Model (From Scratch)* — **Sebastian Raschka**

### Architecture Roadmap

```text
Tokenization (Byte Pair Encoding / Custom Vocab)
       ↓
Embedding Layer + Positional Embeddings
       ↓
Multi-Head Causal Self-Attention
       ↓
Layer Normalization & Residual Connections
       ↓
Feed-Forward Network (GELU / SwiGLU)
       ↓
Stacked Transformer Blocks
       ↓
Output Projection & Softmax
       ↓
Domain Pretraining & Fine-Tuning on University QA
```

### Why Modular Design?

The RAG pipeline established in Module 4 is model-agnostic. The custom transformer can be plugged into the generation step without altering web scraping (Module 1), document OCR (Module 2), or the Pinecone knowledge base (Module 3).

### Current Status

🔜 Planned

---

# 6️⃣ Module 6 — User Interface & Application Deployment

### 🎯 Objective

Provide students with an intuitive, conversational interface available across web and mobile devices.

### Features

* 💬 **Conversational Chat Interface**: Clean chat layout with typing indicators, markdown rendering, and message history.
* 🔗 **Source Cards & Notice Previews**: Direct links to official MAKAUT PDFs with preview snippets.
* 📅 **Deadlines & Important Dates Widget**: Quick-glance panel highlighting upcoming examination, registration, and scholarship dates.
* ⚡ **FastAPI Backend**: Asynchronous REST API serving `/chat`, `/search`, and `/health` endpoints.

### Mockup

```text
┌────────────────────────────────────────────────────────┐
│ 🎓 MAKAUT Intelligent Student Assistant                │
├────────────────────────────────────────────────────────┤
│                                                        │
│ 🧑 Student:                                            │
│ When is the last date for submitting the exam form?    │
│                                                        │
│ 🤖 AI Assistant:                                       │
│ The last date for online examination form submission   │
│ for Odd Semester 2026 is 25 September 2026.            │
│                                                        │
│ 📄 Source Notice: Examination Form Fill-up Notice       │
│ 🔗 View Official Notice: https://makautwb.ac.in/...pdf │
│                                                        │
├────────────────────────────────────────────────────────┤
│ 💬 Ask a question about exams, admissions, dates... [Send] │
└────────────────────────────────────────────────────────┘
```

### Possible Technologies

* **Backend**: FastAPI, Uvicorn, Pydantic
* **Frontend**: Vanilla HTML5/CSS/JavaScript or Modern React/Next.js
* **Deployment**: Docker containerization

### Current Status

🔜 Planned

---

# 🔄 Complete End-to-End Workflow

The final system will work like this:

```text
┌──────────────────────────┐
│    MAKAUT University     │
│        Website           │
└────────────┬─────────────┘
             │
             ▼
      Automatic Scraper
             │
             ▼
        MongoDB
             │
             ▼
      New Notice Found
             │
             ▼
        Download PDF
             │
             ▼
            OCR
             │
             ▼
       Extracted Text
             │
             ▼
           LLM
             │
             ▼
      Structured JSON
             │
             ▼
        MongoDB
             │
             ▼
    Build Retrieval Text
             │
             ▼
   Pinecone Vector Database
             │
             │
      ┌──────┴──────┐
      │             │
      │ Student     │
      │ Question    │
      │             │
      └──────┬──────┘
             ▼
       Query Embedding
             │
             ▼
      Semantic Retrieval
             │
             ▼
      Relevant Documents
             │
             ▼
            LLM
             │
             ▼
       Final Answer
             │
             ▼
        Source Notice
```

---

# 🛠️ Complete Technology Stack

| Layer                  | Technology                          |
| ---------------------- | ----------------------------------- |
| Programming Language   | Python                              |
| Web Scraping           | Requests, BeautifulSoup             |
| Database               | MongoDB / MongoDB Atlas             |
| Database Driver        | PyMongo                             |
| PDF Processing         | PDF tools + OCR                     |
| OCR                    | OCR pipeline                        |
| LLM Framework          | LangChain                           |
| LLM Provider           | Hugging Face                        |
| Current LLM            | GPT-OSS-120B                        |
| Structured Output      | LangChain Output Parser             |
| Document Processing    | LangChain                           |
| Retrieval Text Prep    | Structured Data Synthesizer         |
| Vector Database        | Pinecone (uniai / notices)          |
| Semantic Search        | Pinecone search_records             |
| RAG Pipeline           | LangChain + Pinecone + LLM          |
| Backend                | FastAPI *(planned)*                 |
| Frontend               | Web/Mobile UI *(planned)*           |
| Custom LLM             | GPT-style Transformer *(planned)*   |
| Model Development      | TensorFlow / Python                 |
| Environment Management | Python virtual environment + `.env` |

---

# 🗂️ Planned Project Structure

```text
university-intelligent-qa/
│
├── Module1/
│   ├── scrapper.py
│   ├── module1-revision-notes.md
│   └── requirements.txt
│
├── Module2/
│   ├── main.py
│   ├── ocr.py
│   ├── prompt.py
│   └── README.md
│
├── Module3/
│   ├── main.py
│   ├── search.py
│   └── Readme.md
│
├── Module4_query_retrieval/     # Next: Student query processing & RAG
│   ├── query_processor.py
│   ├── retriever.py
│   └── rag_pipeline.py
│
├── Module5_custom_gpt/          # Planned: Custom LLM from scratch
│   ├── tokenizer/
│   ├── attention/
│   ├── transformer/
│   └── training/
│
├── Module6_interface/           # Planned: Web/API Chat UI
│   ├── app.py
│   └── frontend/
│
├── .env
├── .gitignore
└── README.md
```

> **Note:** Never commit `.env` files, API keys, passwords, MongoDB credentials, or other secrets to GitHub.

---

# 📊 Project Development Status

```text
Module 1  ████████████████████  100% ✅ (Automatic Web Scraper & Portal Monitor)
Module 2  ████████████████████  100% ✅ (OCR & LLM Information Extraction)
Module 3  ████████████████████  100% ✅ (Knowledge Base & Pinecone Vector Store)
Module 4  ░░░░░░░░░░░░░░░░░░░░    0% 🔜 (Student Query Processing & Semantic RAG)
Module 5  ░░░░░░░░░░░░░░░░░░░░    0% 🔜 (Custom GPT Architecture from Scratch)
Module 6  ░░░░░░░░░░░░░░░░░░░░    0% 🔜 (User Interface & Chat Application)
```

---

# 🎯 Knowledge Domains

The system is designed to answer questions related to university information such as:

* 📢 University Notices
* 📝 Examination Procedures
* 💰 Examination Fees
* 🎓 Scholarships
* 📅 Important Dates
* 📋 Registration
* 🧾 Form Submission
* 🏫 Admission Procedures
* 📚 Academic Calendar
* 📊 Results
* 📑 University Circulars
* ⚠️ Student Instructions

The knowledge base will grow automatically as new official notices are published.

---

# 🔐 Data & Security

The project uses official university documents as its primary knowledge source.

Important security practices:

* API keys are stored using environment variables.
* MongoDB credentials are stored in `.env`.
* `.env` is excluded using `.gitignore`.
* Temporary PDF files are removed after processing.
* Each notice is associated with a unique `notice_id`.
* Processed notices are tracked using document status.

Example:

```text
new
 ↓
processing
 ↓
processed
```

Failed documents remain available for retry rather than being incorrectly marked as processed.

---

# ⚡ Why This Project Is Different

Traditional university chatbots often depend on:

```text
Manual PDF Upload
        ↓
Processing
        ↓
Chatbot
```

This project aims for:

```text
University Website
        ↓
Automatic Detection
        ↓
Automatic Processing
        ↓
Automatic Knowledge Update
        ↓
RAG
        ↓
AI University Assistant
```

The goal is to reduce the need for manual knowledge-base maintenance.

---

# 🔮 Future Improvements

Planned improvements include:

### 🤖 Custom LLM Integration

Replace the pretrained LLM with a GPT-style model built from scratch.

### 🌐 Multilingual Support

Support questions in multiple languages commonly used by students.

### 🔄 Continuous Knowledge Updates

Automatically process newly published university notices.

### 📚 Better Retrieval

Improve semantic search using:

* Metadata filtering
* Hybrid search
* Reranking
* Query expansion

### 📱 Student Application

Provide the assistant through a web/mobile application.

### 🔔 Smart Notifications

Notify students about:

* New notices
* Approaching deadlines
* Examination dates
* Scholarship deadlines
* Registration deadlines

---

# 🧪 Example Future Interaction

```text
Student:
"When is the last date for exam form submission?"

        ↓

Query Processing

        ↓

Vector Search

        ↓

Relevant Notice Retrieved

        ↓

LLM

        ↓

AI Assistant:

"The last date for examination form submission is
25 September 2026.

Source:
Examination Form Fill-up Notice"
```

---

# 🧠 Learning Journey Behind the Project

This project combines multiple areas of Computer Science and AI:

```text
Python
   ↓
Web Scraping
   ↓
MongoDB
   ↓
OCR
   ↓
Natural Language Processing
   ↓
Transformers
   ↓
LLMs
   ↓
Embeddings
   ↓
Vector Databases
   ↓
RAG
   ↓
FastAPI
   ↓
AI Application
```

It also provides a practical environment to understand how modern LLM-based applications are built from the ground up.

---

# 📚 References & Learning Resources

### Books

**Build a Large Language Model (From Scratch)**
Sebastian Raschka

Used as the foundation for the future custom GPT implementation.

### Core Concepts

* Transformers
* Self-Attention
* Multi-Head Attention
* Tokenization
* Embeddings
* Vector Search
* Retrieval-Augmented Generation
* Prompt Engineering
* Structured Output
* OCR

---

# 👨‍💻 Project Goal

The ultimate goal is to build a complete university AI assistant that can:

```text
Automatically collect
        ↓
Understand
        ↓
Structure
        ↓
Index
        ↓
Retrieve
        ↓
Reason
        ↓
Answer
```

using official university information.

The project starts with a pretrained LLM to build and validate the complete application pipeline and will later explore replacing the generation component with a **custom GPT-style model built from scratch**.

---

# 🚧 Project Status

**Currently Completed:**

✅ Automatic university notice scraping (`Module1/scrapper.py`)
✅ MongoDB notice storage & duplicate detection
✅ Automatic PDF download pipeline
✅ OCR-based text extraction & artifact cleaning (`Module2/ocr.py`)
✅ LLM-based structured information extraction (`Module2/prompt.py`, `Module2/main.py`)
✅ MongoDB document status lifecycle (`new` → `processed`)
✅ Safe batch processing with fault tolerance & temp file cleanup
✅ Retrieval text construction from structured notice fields
✅ Pinecone vector knowledge base creation (`uniai` index, `notices` namespace)
✅ Integrated vector embeddings & upsert via Pinecone records API (`Module3/main.py`)
✅ Incremental indexing tracking & duplicate prevention in MongoDB
✅ Semantic similarity search verification with test student queries (`Module3/search.py`)

**Currently Working Towards (Next: Student Query & RAG):**

🔜 Student natural language query processing & intent detection (`Module 4`)
🔜 Top-K semantic retrieval from Pinecone with title deduplication (`Module 4`)
🔜 Dynamic context window assembly & prompt engineering (`Module 4`)
🔜 Grounded answer generation with official notice citations & URLs (`Module 4`)
🔜 Custom GPT-style language model built from scratch (`Module 5`)
🔜 Interactive student-facing chat web/mobile interface (`Module 6`)

---

# ⭐ If You Find This Project Interesting

This project is being developed step-by-step as an exploration of:

**Web Scraping → OCR → LLM → Structured Data → Embeddings → Vector Search → RAG → Custom LLM**

Suggestions, ideas, and technical discussions are welcome!

---

## 👨‍💻 Author

**Farhan Akhtar**

B.Tech — Computer Science & Engineering
MAKAUT

---

> 🚀 **Building an AI system that doesn't just answer questions — it automatically learns from the university's latest official information.**
