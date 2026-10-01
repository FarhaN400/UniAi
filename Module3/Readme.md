# 📚 Module 3 — Knowledge Base & Pinecone Vector Storage

> **University AI Assistant — MAKAUT**

Module 3 is responsible for converting the structured information generated in **Module 2** into a searchable knowledge base using **Pinecone**.

The main purpose of this module is to take processed university notices from MongoDB, prepare a retrieval-friendly text representation, and index that information into Pinecone for future semantic retrieval.

---

## 🎯 Objective

The objective of Module 3 is to create the **vector-based knowledge layer** of the University AI Assistant.

Instead of searching university notices using traditional keyword matching, the processed notice information is prepared and indexed in **Pinecone**, allowing the future RAG pipeline to retrieve relevant information based on the meaning of a student's question.

### Module 3 Flow

```text
Processed Notices
       │
       ▼
    MongoDB
       │
       ▼
Build Retrieval Text
       │
       ▼
Pinecone Index
       │
       ▼
Vector Knowledge Base
       │
       ▼
Future Semantic Retrieval
```

---

# 🧩 What Module 3 Does

Module 3 performs four main tasks:

### 1. Connect to MongoDB

The module connects to the existing MongoDB database created in the previous modules.

```text
Database:
university_assistant

Collection:
university_documents
```

Only notices that have successfully completed Module 2 are considered.

```python
query = {
    "status": "processed"
}
```

---

### 2. Build Retrieval Text

The structured information generated in Module 2 is converted into a single retrieval-friendly text.

The following information is extracted:

* Notice title
* Notice type
* Summary
* Key points
* Last date / deadline

For example:

```text
Title:
Semester Examination Form Fill-up

Notice Type:
Examination

Summary:
Students are required to complete the examination form...

Key Points:
Submit the form online
Pay the examination fee
Check the official notice

Deadline:
30 September 2026
```

These pieces of information are combined into one text representation before indexing.

This is handled by:

```python
def build_retrieval_text(notice):
```

---

# 🧠 Retrieval Text Construction

The module first extracts the structured data:

```python
sd = notice["structured_data"]
```

Then it collects the important fields:

```python
parts = [
    sd.get("title", ""),
    sd.get("notice_type", ""),
    sd.get("summary", ""),
]
```

Key points are added when available:

```python
key_points = sd.get("key_points", [])

if key_points:
    parts.append(" ".join(key_points))
```

If a deadline exists, it is explicitly added:

```python
deadline = sd.get("important_dates", {}).get("last_date")

if deadline:
    parts.append(f"Deadline: {deadline}")
```

Finally, all available information is combined into one retrieval text.

---

# 📌 3. Index the Notice in Pinecone

The generated retrieval text is sent to the Pinecone index.

```python
record = {
    "id": notice["notice_id"],
    "text": text,
    "title": notice["structured_data"].get("title"),
    "notice_type": notice["structured_data"].get("notice_type"),
    "url": notice["url"],
}
if year is not None:
    record["year"] = year

index.upsert_records(
    namespace="notices",
    records=[record]
)
```

### Pinecone Record Structure

Each notice is stored with:

| Field         | Type    | Purpose                                               |
| ------------- | ------- | ----------------------------------------------------- |
| `id`          | String  | Unique notice identifier (`notice_id`)                |
| `text`        | String  | Unified retrieval-friendly text representation        |
| `title`       | String  | Official notice title                                 |
| `notice_type` | String  | Type/category of notice (e.g. Examination, Admission) |
| `url`         | String  | Original MAKAUT notice PDF URL                        |
| `year`        | Integer | Extracted 4-digit academic/calendar year (optional)   |

> **Year Extraction:** Extracted via regex `r'(20\d{2})'` from `issue_date` (falling back to `title`). This enables downstream metadata filtering in Module 4 (e.g., retrieving only 2026 notices for *"WBJEE 2026 admission"*).

The records are stored inside the Pinecone namespace:

```text
notices
```

---

# 🔄 4. Track Pinecone Indexing in MongoDB

After a notice is successfully indexed, MongoDB is updated.

```python
{
    "pinecone_indexed": True,
    "pinecone_indexed_at": datetime.now(timezone.utc)
}
```

This creates a connection between the original MongoDB document and its Pinecone indexing status.

Example:

```text
MongoDB Notice

status: processed
pinecone_indexed: True
pinecone_indexed_at: 2026-09-24T...
```

This is important because the system can determine whether a notice has already been indexed.

---

# 🚫 Avoiding Duplicate Indexing

One of the important features of this module is that it does **not repeatedly index the same processed notices by default**.

When:

```python
reindex=False
```

the system searches for notices where:

```python
"status": "processed"
```

and either:

```python
pinecone_indexed
```

does not exist, or:

```python
pinecone_indexed: False
```

The query is:

```python
query = {
    "status": "processed",
    "$or": [
        {"pinecone_indexed": {"$exists": False}},
        {"pinecone_indexed": False}
    ]
}
```

Therefore:

```text
New Processed Notice
        │
        ▼
pinecone_indexed?
   │           │
  No          Yes
   │           │
   ▼           ▼
Index       Skip
```

---

# 🔁 Reindexing Support

The module also supports manually reindexing all processed notices.

If:

```python
reindex=True
```

the query becomes:

```python
query = {
    "status": "processed"
}
```

This allows all processed notices to be indexed again.

Example:

```python
index_all_processed_notices(reindex=True)
```

This can be useful when rebuilding or refreshing the Pinecone knowledge base.

---

# 📦 Batch Processing

The module can process all eligible notices or limit the number of notices during testing.

```python
index_all_processed_notices(limit=10)
```

For example:

```text
limit = 10
        ↓
Fetch 10 processed notices
        ↓
Index them
```

Without a limit:

```python
index_all_processed_notices()
```

all matching notices are processed.

---

# 🗄️ Database Architecture

Module 3 uses two storage systems:

```text
                 ┌─────────────────────┐
                 │      MongoDB        │
                 │                     │
                 │ Original notices    │
                 │ Structured data     │
                 │ Processing status   │
                 │ Indexing status     │
                 └──────────┬──────────┘
                            │
                            ▼
                   Build Retrieval Text
                            │
                            ▼
                 ┌─────────────────────┐
                 │      Pinecone       │
                 │                     │
                 │ Vector knowledge    │
                 │ base                │
                 └─────────────────────┘
```

### MongoDB

MongoDB remains the main document database containing:

* Original notice information
* Structured data
* Processing status
* Pinecone indexing status
* Indexing timestamp

### Pinecone

Pinecone acts as the vector-search layer used for future semantic retrieval.

---

# 🛠️ Tech Stack

| Technology    | Purpose                                 |
| ------------- | --------------------------------------- |
| Python        | Module implementation                   |
| MongoDB       | Store processed university notices      |
| PyMongo       | MongoDB interaction                     |
| Pinecone      | Vector database / semantic search layer |
| python-dotenv | Environment variable management         |
| `datetime`    | Indexing timestamp tracking             |

---

# 🔐 Environment Variables

Create a `.env` file containing the required credentials:

```env
MONGO_URI=your_mongodb_connection_string
PINECONE_API_KEY=your_pinecone_api_key
```

The application loads these values using:

```python
load_dotenv()
```

API keys should **never be committed to GitHub**.

Add `.env` to `.gitignore`:

```gitignore
.env
```

---

# 📂 Module 3 Workflow

The complete execution flow is:

```text
                    MODULE 2
                       │
                       ▼
              Processed Notice
                       │
                       ▼
                   MongoDB
                       │
              status = processed
                       │
                       ▼
             Check Pinecone Status
                 │           │
                Yes          No
                 │           │
                 ▼           ▼
                Skip     Build Retrieval Text
                              │
                              ▼
                           Pinecone
                              │
                              ▼
                    Update MongoDB
                              │
                              ▼
                  pinecone_indexed=True
```

---

# ▶️ Running Module 3

Make sure:

* MongoDB is running
* `.env` contains the required credentials
* Pinecone index `uniai` exists
* Module 2 has processed notices

Then run:

### 1. Index Processed Notices into Pinecone

```bash
cd /Users/farhanakhtar/Desktop/Project/UniAi/Module3
python3 main.py
```

The default execution indexes all unindexed notices:

```python
index_all_processed_notices(reindex=False)
```

The terminal will display something similar to:

```text
Found 25 processed notices to index.

Indexed: Notice Regarding Semester Examination Form Fill-up (year: 2026)
Indexed: Notification for Reporting of WBJEE Candidates (year: 2026)
...

Done. Indexed 25 notices into Pinecone.
```

### 2. Verify Semantic Search (`search.py`)

Run semantic search queries with title deduplication directly against the Pinecone index:

```bash
python3 search.py
```

---

# 🧪 Testing Mode

During development, it is recommended to use a small limit:

```python
index_all_processed_notices(limit=5)
```

This allows the Pinecone indexing process to be tested on a few notices before processing the complete collection.

---

# 🔗 Connection With Other Modules

### Module 1 — Portal Monitoring

```text
MAKAUT Portal
      ↓
Detect New Notice
      ↓
MongoDB
```

### Module 2 — Document Processing

```text
New Notice
    ↓
Download PDF
    ↓
OCR
    ↓
Clean Text
    ↓
LLM Extraction
    ↓
Structured Data
    ↓
MongoDB
```

### Module 3 — Knowledge Base

```text
Structured Data
      ↓
Retrieval Text
      ↓
Pinecone
```

### Module 4 — Retrieval & RAG

```text
Student Question
      ↓
Query Processing
      ↓
Semantic Search
      ↓
Pinecone
      ↓
Relevant Notices
      ↓
Context
```

### Module 5 — LLM / Own GPT

```text
Retrieved Context
      +
Student Question
      ↓
LLM
      ↓
Final Answer
```

### Module 6 — User Interface

```text
Student
   ↓
Web / App Interface
   ↓
AI Assistant
```

---

# 🚀 Current Status

| Module                                 | Status          |
| -------------------------------------- | --------------- |
| Module 1 — Portal Monitoring           | ✅ Completed     |
| Module 2 — Document Processing         | ✅ Completed     |
| **Module 3 — Pinecone Knowledge Base** | **✅ Completed** |
| **Module 4 — Retrieval + RAG**         | **✅ Completed** |
| Module 5 — LLM / Own GPT               | 🔜 In Progress  |
| Module 6 — User Interface              | 🔜 Planned      |

---

# 🎯 Downstream RAG Integration (Module 4)

With Module 3 completed, the processed university notices are indexed in the Pinecone vector knowledge base.

**Module 4 (Student Query Processing & RAG Pipeline)** directly consumes this index:
1. Student questions are classified for intent and temporal constraints.
2. Questions mentioning a specific year (e.g. 2026) trigger a metadata filter on the `year` field in Pinecone.
3. Pinecone's `search_records` retrieves the most relevant notice IDs.
4. Full structured records are fetched from MongoDB, synthesized into prompt context, and answered accurately by the LLM with official citations.

---

# 🌟 Long-Term Vision

The ultimate goal of the University AI Assistant is to create an intelligent university information system that can:

* Automatically detect new university notices
* Process PDF documents
* Extract important information
* Build a searchable knowledge base
* Retrieve relevant information
* Answer student questions naturally
* Provide information from official university documents
* Continuously update as new notices are published

The long-term architecture is:

```text
MAKAUT Portal
      ↓
Automatic Monitoring
      ↓
Document Processing
      ↓
Knowledge Base
      ↓
Pinecone
      ↓
Retrieval
      ↓
RAG
      ↓
LLM
      ↓
University AI Assistant
```

---

## 👨‍💻 Project

**University AI Assistant**

Built as a final-year AI/ML project with the goal of combining:

**Web Scraping + OCR + LLMs + Embeddings + Vector Database + RAG + Generative AI**

---

> **Module 3 completed 🚀 — The university notices are now ready to become searchable knowledge.**
