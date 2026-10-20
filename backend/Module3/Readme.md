# 📚 Module 3 — Knowledge Base & Pinecone Vector Storage

> **University AI Assistant (UniAI) — MAKAUT**  
> Vectorizing structured university intelligence, Pinecone integrated embedding indexing, year-aware metadata tagging, and MongoDB synchronization.

Module 3 converts the structured JSON intelligence produced by **Module 2** into a high-performance vector knowledge base in **Pinecone**. It queries verified processed circulars from MongoDB, synthesizes a retrieval-optimized text representation capturing critical dates, fees, actions, and key points, indexes them with year-aware metadata into Pinecone's serverless vector store, and synchronizes the indexing state back into MongoDB.

---

## 🎯 Key Objectives

1. **Semantic Vector Knowledge Layer:** Enables semantic search over official university notices, allowing students to retrieve circulars based on conceptual intent rather than rigid keyword matching.
2. **Comprehensive Retrieval Text Construction (`build_retrieval_text`):** Aggregates notice title, category, summary, required actions, all key points, start/last dates, and official fee amounts into an information-dense text representation.
3. **Year-Aware Metadata Tagging (`extract_year`):** Extracts 4-digit academic and calendar years (e.g. `2025`, `2026`) from issue dates and titles, tagging records in Pinecone to support strict temporal filtering in Module 4.
4. **Integrated Pinecone Embeddings:** Leverages Pinecone's serverless `upsert_records` API, which automatically embeds the document text into dense vectors upon ingestion.
5. **Quality-Controlled Ingestion:** Filters out circulars flagged for human review (`quality_review_required: True`), indexing only thoroughly validated structured notices.
6. **Idempotent Synchronization:** Tracks `pinecone_indexed: True` and timestamp in MongoDB, preventing duplicate upserts while providing complete reindexing capabilities (`reindex=True`).

---

## 🏗️ Architecture & Data Flow

```text
                  MongoDB: university_documents
              (status: "processed", quality_review != true)
                                │
                                ▼
                   Fetch Eligible Documents
             (query: pinecone_indexed is false/missing)
                                │
                                ▼
                     build_retrieval_text()
              - Title & Notice Type
              - Executive Summary & Action Required
              - All Key Points
              - Start & Last Dates (Deadlines)
              - Official Fees (Amount & Currency)
                                │
                                ▼
                        extract_year()
              (Regex: 20xx from issue_date or title)
                                │
                                ▼
                    Construct Pinecone Record
              { id, text, title, notice_type, url, year }
                                │
                                ▼
                 Pinecone Serverless Index (uniai)
                   Namespace: "notices"
              (index.upsert_records with integrated embeddings)
                                │
                                ▼
                    Update MongoDB Document
              - pinecone_indexed: True
              - pinecone_indexed_at: UTC timestamp
                                │
                                ▼
                   Verified Semantic Knowledge Base
                    (Ready for Module 4 RAG Pipeline)
```

---

## 🧠 Retrieval Text Construction (`build_retrieval_text`)

The text representation indexed into Pinecone is engineered to maximize retrieval relevance for student queries:

```python
def build_retrieval_text(notice):
    sd = notice.get("structured_data") or {}

    parts = [
        sd.get("title"),
        sd.get("notice_type"),
        sd.get("summary"),
        sd.get("action_required"),
    ]

    # Include key points
    key_points = sd.get("key_points") or []
    parts.extend(key_points)

    # Include important dates
    dates = sd.get("important_dates") or {}
    if dates.get("start_date"):
        parts.append(f"Start date: {dates['start_date']}")
    if dates.get("last_date"):
        parts.append(f"Last date: {dates['last_date']}")

    # Include fees
    fees = sd.get("fees") or {}
    if fees.get("amount") is not None:
        amount = fees["amount"]
        currency = fees.get("currency") or ""
        parts.append(f"Fee: {amount} {currency}".strip())

    return "\n".join(
        str(part).strip()
        for part in parts
        if part is not None and str(part).strip()
    )
```

### Example Generated Retrieval Text:
```text
Notice Regarding Semester Examination Form Fill-up 2026
Examination
Official notification regarding online examination form submission and fee payment for upcoming semester examinations.
Submit exam form online and pay fee before deadline.
Online portal opens on 16 September 2026.
Last date of submission without late fine is 30 September 2026.
Admit cards will be available 3 days prior to commencement.
Start date: 16-09-2026
Last date: 30-09-2026
Fee: 1200 INR
```

---

## 📌 Pinecone Record Structure & Upsert

Each record is upserted into the `uniai` index under the `notices` namespace:

```python
record = {
    "id": notice["notice_id"],
    "text": text,
    "title": sd.get("title") or "",
    "notice_type": sd.get("notice_type") or "",
    "url": notice.get("url") or "",
}

if year is not None:
    record["year"] = year

index.upsert_records(
    namespace="notices",
    records=[record]
)
```

### Schema Attributes:
| Field | Type | Description |
|---|---|---|
| `id` | String | Unique SHA-256 identifier (`notice_id`) matching MongoDB. |
| `text` | String | Structured retrieval text vectorized by Pinecone's integrated embedding model. |
| `title` | String | Standardized notice title. |
| `notice_type` | String | Category (e.g. `Examination`, `Admission`, `Discipline`, `Scholarship`). |
| `url` | String | Source URL of official university notice PDF. |
| `year` | Integer | 4-digit academic/calendar year (e.g. `2025`, `2026`), enabling metadata-filtered queries. |

---

## 🛡️ Ingestion Quality & Duplicate Prevention

### 1. Quality Review Filter
Notices flagged for human quality review during Module 2 chunking are excluded from vector indexing until approved:
```python
query = {
    "status": "processed",
    "quality_review_required": {"$ne": True},
    "structured_data": {"$type": "object"}
}
```

### 2. Idempotent Indexing
To avoid redundant API calls and vector re-embeddings, the pipeline checks for prior indexing:
```python
if not reindex:
    query["$or"] = [
        {"pinecone_indexed": {"$exists": False}},
        {"pinecone_indexed": False}
    ]
```

### 3. Verification Post-Upsert
MongoDB status is updated only after Pinecone confirms the upsert:
```python
result = notices_collection.update_one(
    {"_id": notice["_id"]},
    {
        "$set": {
            "pinecone_indexed": True,
            "pinecone_indexed_at": datetime.now(timezone.utc)
        }
    }
)
if result.matched_count != 1:
    raise RuntimeError("Pinecone upsert succeeded, but MongoDB indexing status could not be updated")
```

---

## 🔍 Semantic Search Verification (`search.py`)

A standalone verification utility `search.py` is provided to test semantic retrieval and similarity scores from the terminal:

```python
from main import index

def search_notices(question, top_k=3):
    results = index.search_records(
        namespace="notices",
        query={
            "inputs": {"text": question},
            "top_k": top_k
        }
    )
    # Deduplicates hits by normalized title and prints score ranking
```

---

## 📂 Source Code Files

| File | Description |
|---|---|
| [`main.py`](main.py) | **Vector Ingestion Engine:** Retrieval text compiler, year extractor, Pinecone serverless upsert client, MongoDB status synchronizer, and batch summary reporter. |
| [`search.py`](search.py) | **Vector Search Verification Utility:** Standalone query tester using `index.search_records`, title deduplication, and score ranking. |
| [`Readme.md`](Readme.md) | Module 3 technical documentation and architecture guide. |

---

## ⚙️ Environment Configuration

Set the following credentials in your root `.env` file:

```env
MONGO_URI=mongodb+srv://<username>:<password>@cluster0.mongodb.net/?retryWrites=true&w=majority
PINECONE_API_KEY=pcsk_...
```

---

## ▶️ How to Run

### 1. Ingest Processed Notices into Pinecone

From the project root:
```bash
python3 backend/Module3/main.py
```

From the module directory:
```bash
cd backend/Module3
python3 main.py
```

**Example Summary Output:**
```text
=======================================================
UniAI Module 3 | Pinecone Indexing
=======================================================
Found 28 eligible notices to index.

[1/28] Notice Regarding Semester Examination Form Fill-up
  -> Indexed: Notice Regarding Semester Examination Form Fill-up (year: 2026)
[2/28] Notification for WBJEE Reporting
  -> Indexed: Notification for WBJEE Reporting (year: 2026)
...

=======================================================
UniAI Module 3 | Indexing Summary
=======================================================
Total selected : 28
Indexed        : 28
Failed         : 0
=======================================================
```

### 2. Verify Semantic Search (`search.py`)

Test semantic retrieval directly from the terminal:

```bash
python3 backend/Module3/search.py
```

**Example Output:**
```text
Query: 'what documents do I need for WBJEE 2026 admission'
Score: 0.884 | Notification for reporting of candidates for admission through WBJEE-2026
Score: 0.742 | Admission Notification 2026
Score: 0.698 | In-House Direct Admission Notice 2026-2027
```

---

## ✅ Validation Checklist

- [x] Connected to MongoDB database `university_assistant` and collection `university_documents`.
- [x] Connected to Pinecone serverless index `uniai`, namespace `notices`.
- [x] Comprehensive retrieval text synthesizes all critical fields (title, summary, actions, key points, dates, fees).
- [x] Automatic validation prevents indexing records with empty retrieval text.
- [x] Extracted 4-digit years tagged as numeric metadata (`year`) for downstream filtering.
- [x] Ingestion skips notices flagged with `quality_review_required: True`.
- [x] MongoDB document tracks `pinecone_indexed: True` and UTC timestamp.
- [x] Idempotency confirmed: repeated runs skip already-indexed notices unless `reindex=True`.
- [x] Semantic search test script `search.py` confirms successful record retrieval and score ranking.
