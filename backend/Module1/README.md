# 🌐 Module 1 — Automatic University Notice Collection & Portal Monitoring

> **University AI Assistant (UniAI) — MAKAUT**  
> Continuous, automated monitoring of official university notice boards with deterministic deduplication, database-level idempotency, and in-place PDF content change detection.

Module 1 is the ingestion entry point of the **UniAI** pipeline. It continuously scans the official Maulana Abul Kalam Azad University of Technology (MAKAUT) notice portal, discovers newly published circulars without requiring manual document uploads, extracts essential notice metadata and URLs, detects in-place PDF revisions, and persists records into MongoDB.

---

## 🎯 Key Objectives

1. **Automated Monitoring:** Periodically inspects the official university notice board (`https://makautwb.ac.in/page.php?id=340`) for newly posted circulars.
2. **Deterministic Deduplication:** Computes cryptographic SHA-256 identifiers from normalized notice URLs, guaranteeing document identity across pipeline stages.
3. **Database Idempotency:** Stores notices in MongoDB using atomic upsert operations (`$setOnInsert`) and unique indexes, ensuring that repeated runs never duplicate records or overwrite initial detection timestamps.
4. **In-Place PDF Revision Detection:** Checks existing processed notice PDFs using streaming SHA-256 content hashing (`_pdf_digest`) to detect circulars updated at the same URL without a URL change.
5. **Clean Pipeline Handoff:** Flags new and updated circulars with `status: "new"`, ready for downstream PDF acquisition, OCR, and structured information extraction in **Module 2**.

---

## 🏗️ Architecture & Workflow

```text
                       MAKAUT Notice Portal
                (https://makautwb.ac.in/page.php?id=340)
                                 │
                                 ▼
                       HTTP GET Request
                  (requests with 25s timeout)
                                 │
                                 ▼
                          HTML Parsing
                     (BeautifulSoup4 / lxml)
                                 │
                                 ▼
                    Notice Tag Identification
                      (a.text-danger[href])
                                 │
                                 ▼
                Extract Title, URL, and "NEW" Badge
                 - urljoin(BASE_URL, href)
                 - Verify official MAKAUT hostname
                 - Check sibling <img> for 'new-08-june'
                                 │
                                 ▼
                   Deterministic SHA-256 Hashing
                   notice_id = SHA256(notice_url)
                                 │
                                 ▼
                     MongoDB Upsert Operation
                   (Collection: university_documents)
                Match: {"notice_id": notice["notice_id"]}
                Update: {"$setOnInsert": payload, "$set": refresh_fields}
                                 │
                 ┌───────────────┴───────────────┐
                 ▼                               ▼
        Genuinely New Notice            Existing Notice
         - status: "new"                 - Preserves initial detected_at
         - detected_at: UTC timestamp    - Updates last_seen_at
         - Handoff to Module 2           - Updates flagged_new_on_site
                                                 │
                                                 ▼
                                     Optional In-Place Check
                                  recheck_existing_pdf_versions()
                                  (Compares PDF SHA-256 checksum)
```

---

## 🔍 Site Investigation & HTML Extraction

During portal inspection, MAKAUT notice endpoints were analyzed:

| Endpoint | Result | Purpose in UniAI |
|---|---|---|
| `makautwb.ac.in/page.php?id=340` | **Primary server-rendered notice board** | **Target source:** Pure HTML table containing official circulars, exam notices, and admission updates. |
| `makautexam.net` | Secondary examination portal | Exam schedules, routine downloads, and admit cards. |
| `www.makautwb.ac.in` (root) | Dynamic landing portal | University announcements and homepage banners. |

### Confirmed HTML Pattern

On the target notice page, notices follow a distinct DOM structure:

```html
<a class="text-danger" href="datas/users/0-exam_schedule_2026.pdf">
    <font color="blue">Notice Regarding Semester Examination Form Fill-up 2026</font>
</a>
&nbsp;
<img src="images/new-08-june.gif" border="0">
<br/><br/>
```

- **Notice Links:** Always styled with CSS class `a.text-danger[href]`.
- **URL Resolution:** Links appear as relative (`datas/...`), root-relative (`/datas/...`), or absolute URLs. All paths are resolved via `urllib.parse.urljoin(BASE_URL, href)`.
- **Domain Verification:** URLs are validated to ensure they originate strictly from official MAKAUT domains (`makautwb.ac.in` or `www.makautwb.ac.in`).
- **"NEW" Indicator:** When a flashing "NEW" gif badge (`images/new-08-june.gif`) is present as an adjacent sibling image, `flagged_new_on_site` is set to `True`.

---

## 🔐 Deterministic Notice Identification & Idempotency

### 1. SHA-256 Unique Identifier
Each notice receives an immutable, deterministic `notice_id` computed from its normalized URL:

```python
notice["notice_id"] = hashlib.sha256(notice["url"].encode("utf-8")).hexdigest()
```

- Deterministic hashing guarantees that the same URL always yields the exact same 64-character hexadecimal ID.
- Acts as the primary database key and vector reference across all modules.

### 2. MongoDB Upsert with `$setOnInsert`
To ensure the crawler can run on a schedule (e.g., every 3 hours via GitHub Actions) without corrupting existing records or resetting extraction progress:

```python
notices_collection.create_index("notice_id", unique=True)

result = notices_collection.update_one(
    {"notice_id": notice["notice_id"]},
    {
        "$setOnInsert": {
            **insert_only,
            "detected_at": now,
            "status": "invalid" if invalid else "new",
            "pinecone_indexed": False,
            "processing_attempts": 0,
        },
        "$set": {
            "last_seen_at": now,
            "flagged_new_on_site": notice["flagged_new_on_site"],
        },
    },
    upsert=True,
)
```

- **`$setOnInsert`**: Sets initial metadata (`status: "new"`, `detected_at`, `pinecone_indexed: False`, `processing_attempts: 0`) **only** when a new notice is first inserted.
- **`$set`**: Refreshes dynamic fields (`last_seen_at` and `flagged_new_on_site`) without touching `status: "processed"` or structured extraction outputs.
- **Unique Index**: Database-level unique constraint on `notice_id` prevents duplicate insertions under concurrent or repeated executions.

---

## 📄 In-Place PDF Content Revision Detection

University administrators occasionally replace the contents of an existing notice PDF without changing its URL. Module 1 provides streaming hash verification to detect these updates:

```python
def _pdf_digest(url):
    """Compute SHA-256 checksum of an official PDF via streaming with magic-byte check."""
    # Enforces HTTPS, 25 MB max size, and %PDF- header validation
...

def recheck_existing_pdf_versions(limit=0):
    """Check a bounded sample of processed PDF hashes against live portal content."""
```

- **Streaming Verification:** Downloads the PDF in 64 KB chunks up to a 25 MB limit without saving large files to disk.
- **Magic-Byte Check:** Confirms the file begins with `%PDF-`.
- **Change Handling:** If the newly calculated SHA-256 hash differs from the stored `pdf_sha256`, the notice status is reset to `"new"`, `pinecone_indexed` is reset to `False`, and `content_change_detected_at` is stamped for re-extraction by Module 2.

---

## 🛡️ Fault Tolerance & Known Invalid Notice Quarantine

Corrupted files or broken links published on the university portal are handled gracefully:

```python
INVALID_NOTICE_IDS = {
    "a9dd4d2604d2a16028d40a7213745cb93ddef51fe8eb44877b3c75ab5b2af333"
}
```

- Known invalid notice IDs are automatically flagged with `status: "invalid"` and logged with `processing_error`.
- Downstream modules (Module 2, Module 3, Module 4) query only eligible statuses, preventing pipeline halts.

---

## 🗄️ MongoDB Document Schema

When a notice is first ingested by Module 1, its document in the `university_documents` collection appears as follows:

```json
{
  "_id": "ObjectId(...)",
  "notice_id": "c701185f86386569cd6f34f6b5d033073f410a21f74847c3f8d4f954a7fe1b77",
  "title": "Notice Regarding Semester Examination Form Fill-up 2026",
  "url": "https://makautwb.ac.in/datas/users/0-exam_form_2026.pdf",
  "flagged_new_on_site": true,
  "status": "new",
  "detected_at": "2026-09-07T20:01:44.833Z",
  "last_seen_at": "2026-09-07T20:01:44.833Z",
  "pinecone_indexed": false,
  "processing_attempts": 0
}
```

### Document Status Progression

```text
status: "new"  ──(Module 2)──►  status: "processed"  ──(Module 3)──►  pinecone_indexed: true
      │                                │
      ▼                                ▼
status: "invalid"               status: "failed" (retried up to MAX_ATTEMPTS)
```

---

## 📂 Source Code Files

| File | Description |
|---|---|
| [`scrapper.py`](scrapper.py) | **Main Monitor Script:** Portal crawler, HTML parser, SHA-256 hasher, MongoDB upsert, and in-place PDF revision checker. |
| [`README.md`](README.md) | Module 1 technical documentation and operational guide. |

---

## ⚙️ Environment Configuration

Module 1 requires a MongoDB Atlas connection string in your root `.env` file:

```env
MONGO_URI=mongodb+srv://<username>:<password>@cluster0.mongodb.net/?retryWrites=true&w=majority
```

---

## ▶️ How to Run

### 1. Run from the Repository Root

```bash
python3 backend/Module1/scrapper.py
```

### 2. Run from the Module Directory

```bash
cd backend/Module1
python3 scrapper.py
```

### 3. Programmatic Invocation

```python
from backend.Module1.scrapper import run_monitor_cycle, recheck_existing_pdf_versions

# Run discovery
report = run_monitor_cycle()
print(report)  # {'seen': 187, 'new': 2, 'existing': 185}

# Check for in-place PDF updates
recheck_report = recheck_existing_pdf_versions(limit=5)
print(recheck_report)  # {'checked': 5, 'changed': 0, 'errors': 0}
```

---

## ✅ Validation Checklist

- [x] Portal HTML fetched cleanly with timeout protection (25s).
- [x] Links verified strictly against official MAKAUT domains (`makautwb.ac.in`).
- [x] URLs resolved to absolute addresses via `urllib.parse.urljoin`.
- [x] Deterministic SHA-256 identifier (`notice_id`) guarantees record deduplication.
- [x] MongoDB collection `university_documents` enforces a unique index on `notice_id`.
- [x] Atomic upsert (`$setOnInsert`) preserves initial `detected_at` timestamps across runs.
- [x] In-place PDF content change detection (`_pdf_digest`) monitors modified circulars.
- [x] Known broken/corrupt circulars quarantined under `status: "invalid"`.
- [x] Clean handoff: new circulars saved with `status: "new"` for Module 2.
