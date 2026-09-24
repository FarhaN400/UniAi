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
                    │        MongoDB            │
                    │                          │
                    │ Raw Text + Structured    │
                    │ JSON + Metadata          │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │     MODULE 3             │
                    │ Chunking + Embeddings    │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │     MODULE 4             │
                    │      Vector Store        │
                    │                          │
                    │ Embeddings + Metadata    │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │     MODULE 5             │
                    │    Query Processing      │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │     MODULE 6             │
                    │       LLM / RAG          │
                    │                          │
                    │ Retriever → LLM → Answer │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │     MODULE 7             │
                    │ Response Validation      │
                    │ + Source Information     │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │     MODULE 8             │
                    │      User Interface      │
                    │      Chat Application    │
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

---

# 4️⃣ Module 4 — Vector Database / Knowledge Base

### 🎯 Objective

Store document embeddings so that the system can perform semantic search.

Traditional keyword search may fail when the student's wording differs from the wording used in the notice.

### Example

Notice:

> "The last date for submission of the examination form is 25 September."

Student:

> "When can I submit the exam form until?"

Keyword matching may not find an exact match.

Semantic embeddings allow the system to understand that both statements are related.

### Workflow

```text
Document Chunk
      ↓
Embedding Model
      ↓
Vector
      ↓
Vector Database
```

Each vector will also contain metadata such as:

```json
{
  "notice_id": "...",
  "title": "...",
  "category": "Examination",
  "source_url": "...",
  "chunk_id": "..."
}
```

### Technologies

Planned:

* Vector Database
* Embedding Model
* LangChain
* MongoDB metadata

### Current Status

🔜 Planned

---

# 5️⃣ Module 5 — Query Processing

### 🎯 Objective

Understand the student's question and retrieve the most relevant university information.

### Workflow

```text
Student Question
       ↓
Query Processing
       ↓
Query Embedding
       ↓
Vector Search
       ↓
Top Relevant Chunks
```

### Example

Student asks:

> "What is the last date for scholarship application?"

The system searches the vector database and retrieves the chunks containing scholarship deadlines and related instructions.

### Planned Components

* Query embedding
* Similarity search
* Top-K retrieval
* Metadata filtering
* Relevant context selection

### Current Status

🔜 Planned

---

# 6️⃣ Module 6 — LLM + Retrieval-Augmented Generation

### 🎯 Objective

Generate answers using retrieved university information rather than relying only on the LLM's pretrained knowledge.

### RAG Pipeline

```text
Student Question
       ↓
Vector Search
       ↓
Relevant University Documents
       ↓
Context
       ↓
LLM
       ↓
Generated Answer
```

### Why RAG?

University information changes frequently.

For example:

```text
Exam Deadline
Scholarship Deadline
Registration Date
Admission Procedure
Form Submission Date
```

The system should answer using the **latest retrieved university documents**.

RAG allows the LLM to use the university's knowledge base as context.

---

# 🤖 LLM Strategy

The project is intentionally being developed in two stages.

## Phase 1 — Pretrained LLM

Initially, the system will use a pretrained LLM for answer generation and information extraction.

Current LLM integration:

```text
Hugging Face
      ↓
GPT-OSS-120B
      ↓
LangChain
```

This allows the complete application and RAG pipeline to be developed first.

---

# 🧠 Phase 2 — Custom GPT Model

One of the major future goals of this project is to replace the pretrained generation model with a **custom GPT-style language model built from scratch**.

The model development follows:

📖 *Build a Large Language Model (From Scratch)*
**Sebastian Raschka**

### Planned Model Development

```text
Tokenization
      ↓
Embeddings
      ↓
Positional Embeddings
      ↓
Self-Attention
      ↓
Multi-Head Attention
      ↓
Feed-Forward Network
      ↓
Transformer Blocks
      ↓
GPT Architecture
      ↓
Pretraining / Fine-Tuning
      ↓
University QA System
```

The goal is to make the final architecture modular so that the LLM component can be replaced without rebuilding the complete data and retrieval pipeline.

---

# 7️⃣ Module 7 — Response Validation & Source Handling

### 🎯 Objective

Improve reliability and transparency of generated answers.

The response layer will verify that the generated answer is grounded in retrieved university information.

### Planned Flow

```text
Retrieved Context
       ↓
LLM Answer
       ↓
Validation
       ↓
Source Information
       ↓
Final Response
```

The system can provide information such as:

```text
Answer:
The last date for submission is 25 September 2026.

Source:
Examination Form Fill-up Notice
```

This makes the system more transparent and useful for students.

### Current Status

🔜 Planned

---

# 8️⃣ Module 8 — User Interface

### 🎯 Objective

Provide students with a simple conversational interface.

### Example

```text
┌─────────────────────────────────────────┐
│       🎓 University AI Assistant        │
├─────────────────────────────────────────┤
│                                         │
│ Student:                                │
│ What is the last date for exam form?    │
│                                         │
│ AI Assistant:                           │
│ The last date is 25 September 2026.     │
│                                         │
│ Source: Examination Notice              │
│                                         │
├─────────────────────────────────────────┤
│ Ask your question...              Send  │
└─────────────────────────────────────────┘
```

### Possible Technologies

* Frontend / Chat UI
* Python backend
* FastAPI
* REST API
* Mobile/Web interface

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
          Chunking
             │
             ▼
        Embeddings
             │
             ▼
       Vector Database
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
| Chunking               | LangChain Text Splitters            |
| Embeddings             | Embedding Model                     |
| Vector Search          | Vector Database                     |
| RAG                    | LangChain + Vector Store            |
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
├── module1_scraper/
│   ├── scraper.py
│   └── requirements.txt
│
├── module2_document_processing/
│   ├── main.py
│   ├── ocr.py
│   ├── prompt.py
│   └── requirements.txt
│
├── module3_knowledge_base/
│   ├── main.py
│   ├── search.py
│   └── Readme.md
│
├── module4_vector_store/
│   ├── vector_store.py
│   └── ...
│
├── module5_query/
│   ├── retriever.py
│   └── ...
│
├── module6_rag/
│   ├── rag_chain.py
│   └── ...
│
├── module7_response/
│   ├── validator.py
│   └── ...
│
├── module8_interface/
│   ├── api/
│   ├── frontend/
│   └── ...
│
├── custom_gpt/
│   ├── tokenizer/
│   ├── attention/
│   ├── transformer/
│   └── training/
│
├── .env
├── .gitignore
└── README.md
```

> **Note:** Never commit `.env` files, API keys, passwords, MongoDB credentials, or other secrets to GitHub.

---

# 📊 Project Development Status

```text
Module 1  ████████████████████  100% ✅
Module 2  ████████████████████  100% ✅
Module 3  ████████████████████  100% ✅
Module 4  ░░░░░░░░░░░░░░░░░░░░    0% 🔜
Module 5  ░░░░░░░░░░░░░░░░░░░░    0% 🔜
Module 6  ░░░░░░░░░░░░░░░░░░░░    0% 🔜
Module 7  ░░░░░░░░░░░░░░░░░░░░    0% 🔜
Module 8  ░░░░░░░░░░░░░░░░░░░░    0% 🔜
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

✅ Automatic university notice scraping
✅ MongoDB notice storage
✅ Duplicate notice detection
✅ Automatic PDF processing pipeline
✅ OCR-based text extraction
✅ LLM-based information extraction
✅ Structured JSON generation
✅ MongoDB structured-data storage
✅ Processing status management
✅ Batch processing with error handling
✅ Retrieval text construction from structured data
✅ Pinecone vector knowledge base indexing
✅ MongoDB Pinecone indexing tracking & deduplication
✅ Semantic search & retrieval verification

**Currently Working Towards:**

🔜 Semantic retrieval & RAG pipeline
🔜 Response validation & source grounding
🔜 Student-facing chatbot
🔜 Custom GPT integration

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
