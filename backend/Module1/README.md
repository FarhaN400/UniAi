# 🌐 Module 1 — Automatic University Notice Collection & Portal Monitoring

> **University AI Assistant — MAKAUT**  
> Continuous, automated monitoring of official university notice boards with deterministic deduplication and database-level idempotency.

Module 1 is the entry point of the **UniAI** pipeline. It automatically monitors the official MAKAUT notice portal, detects newly published notices without requiring manual document uploads, extracts essential notice metadata and URLs, and persists them into MongoDB.

---

## 🎯 Objective

Traditional university information systems require administrators to manually upload notices and PDFs. Module 1 eliminates this manual overhead:
1. **Automated Monitoring:** Periodically scans the official university notices page.
2. **Deterministic Deduplication:** Generates unique cryptographic identifiers for each notice.
3. **Database Idempotency:** Stores notices in MongoDB using upserts and unique indexes, guaranteeing that repeated runs never duplicate records or overwrite initial detection timestamps.
4. **Handoff to Module 2:** Flags new documents with `status: "new"`, ready for downstream PDF download, OCR, and LLM structuring.

---

## 🏗️ Architecture & Workflow

```text
                      MAKAUT Notice Portal
               (https://makautwb.ac.in/page.php?id=340)
                                │
                                ▼
                       HTTP GET Request
                     (requests with timeout)
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
             Update: {"$setOnInsert": notice, upsert=True}
                                │
                ┌───────────────┴───────────────┐
                ▼                               ▼
       Genuinely New Notice            Existing Notice
        - status: "new"                 - Untouched
        - detected_at: UTC timestamp    - Preserves original timestamp
        - Handoff to Module 2           - Ignored
```

---

## 🔍 Site Investigation & HTML Extraction

During initial portal analysis, several endpoints were inspected:

| Endpoint | Result | Notes |
|---|---|---|
| `makautexam.net` | Secondary portal | Plain `<a>` tags, exam-specific updates |
| `www.makautwb.ac.in` (root) | Dynamic / JS-rendered | Requires headless browser (Selenium/Playwright) |
| `makautwb.ac.in/page.php?id=340` | **Primary server-rendered notice board** | **Target source:** Contains ~180+ notices in pure HTML |

### Confirmed HTML Pattern

On the target notice page, notices follow a distinct DOM structure:

```html
<a class="text-danger" href="datas/users/0-file.pdf">
    <font color="blue">Notice Title Text</font>
</a>
&nbsp;
<img src="images/new-08-june.gif" border="0">
<br/><br/>
```

- **Notice Links:** Always have the CSS class `a.text-danger[href]`.
- **URL Resolution:** Links appear in relative (`datas/...`), root-relative (`/datas/...`), and absolute formats. All URLs are normalized using `urllib.parse.urljoin`.
- **New Indicator:** When a flashing "NEW" gif badge (`images/new-08-june.gif`) is present as a sibling image, `flagged_new_on_site` is set to `True`.

---

## 🔐 Deterministic Notice Identification & Idempotency

### 1. SHA-256 Unique Identifier
Each notice receives a deterministic `notice_id` computed from its normalized URL:

```python
notice["notice_id"] = hashlib.sha256(notice["url"].encode()).hexdigest()
```

- Deterministic hashing ensures that the same URL always yields the exact same 64-character hexadecimal ID.
- Prevents collisions and acts as the document primary key.

### 2. MongoDB Upsert with `$setOnInsert`
To ensure the monitor can run every 30 minutes without corrupting data or resetting detection dates:

```python
notices_collection.create_index("notice_id", unique=True)

result = notices_collection.update_one(
    {"notice_id": notice["notice_id"]},
    {"$setOnInsert": notice},
    upsert=True
)
```

- **`upsert=True`**: Inserts the document if it does not exist; skips if it already exists.
- **`$setOnInsert`**: Fields (such as `detected_at` and `status: "new"`) are written **only** on initial insertion. Subsequent runs do not overwrite existing progress.
- **Unique Index**: Enforces database-level uniqueness, preventing race conditions or duplicate entries even under concurrent executions.

---

## 🛡️ Fault Tolerance & Invalid Notice Handling

Corrupt PDFs or broken links published on the university portal are handled gracefully:

```python
INVALID_NOTICE_IDS = {
    "a9dd4d2604d2a16028d40a7213745cb93ddef51fe8eb44877b3c75ab5b2af333"
}
```

- Known invalid notices are automatically flagged with `status: "invalid"`.
- Error diagnostics (`processing_error`, `invalid_pdf_url`) are logged in the document.
- Downstream modules (Module 2, 3, 4) query only `status: "new"` or `status: "processed"`, preventing pipeline failures.

---

## 🗄️ MongoDB Document Schema

When a notice is first inserted by Module 1, it has the following schema:

```json
{
  "_id": "ObjectId(...)",
  "notice_id": "c701185f86386569cd6f34f6b5d033073f410a21f74847c3f8d4f954a7fe1b77",
  "title": "Notice Regarding Semester Examination Form Fill-up 2026",
  "url": "https://makautwb.ac.in/datas/users/0-exam_form_2026.pdf",
  "flagged_new_on_site": true,
  "status": "new",
  "detected_at": "2026-09-07T20:01:44.833Z"
}
```

### Document Status Lifecycle

```text
status: "new"       ──(Module 2)──►  status: "processed"  ──(Module 3)──►  pinecone_indexed: True
       │                                     │
       ▼                                     ▼
status: "invalid"                     status: "error"
```

---

## 📂 File Structure

| File | Purpose |
|---|---|
| [`scrapper.py`](file:///Users/farhanakhtar/Desktop/Project/UniAi/Module1/scrapper.py) | Main scraper script: portal HTTP fetch, HTML parsing, hashing, and MongoDB upsert |
| [`module1-revision-notes.md`](file:///Users/farhanakhtar/Desktop/Project/UniAi/Module1/module1-revision-notes.md) | Technical revision notes, site investigation logs, and interview prep |
| `README.md` | Comprehensive module documentation and guide |

---

## ⚙️ Environment Configuration

Module 1 requires a MongoDB connection string defined in the root `.env` file:

```env
MONGO_URI=mongodb+srv://<username>:<password>@cluster0.mongodb.net/?retryWrites=true&w=majority
```

---

## ▶️ How to Run

### 1. Run the Scraper

```bash
cd /Users/farhanakhtar/Desktop/Project/UniAi/Module1
python3 scrapper.py
```

### 2. Expected Output

On initial run (empty database):
```text
Checking university portal...

Found 187 notices on the page.
Existing notices: 0
New notices: 187

NEW:
- Notice Regarding Semester Examination Form Fill-up 2026
  https://makautwb.ac.in/datas/users/0-exam_form_2026.pdf
...
```

On subsequent runs (no changes on portal):
```text
Checking university portal...

Found 187 notices on the page.
Existing notices: 187
New notices: 0

No new notices this run.
```

---

## ✅ Validation Checklist

- [x] Portal HTML fetched successfully with timeout protection.
- [x] Links resolved cleanly to absolute URLs via `urllib.parse.urljoin`.
- [x] Deterministic SHA-256 notice IDs prevent duplicate records.
- [x] MongoDB collection `university_documents` enforces unique index on `notice_id`.
- [x] Upsert logic uses `$setOnInsert` to preserve initial `detected_at` timestamps.
- [x] Known broken/invalid notice URLs isolated with `status: "invalid"`.
- [x] Verified zero duplicates across repeated runs (idempotency confirmed).
- [x] Clean handoff: new notices stored with `status: "new"` for Module 2.
