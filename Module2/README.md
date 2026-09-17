# Module 2 — Document Processing & Structured Extraction: Revision Cheat Sheet

## What Module 2 does (one line)
Automatically retrieves unprocessed university notices (`status: "new"`) from MongoDB, downloads and OCR-processes each PDF, extracts structured JSON metadata using an LLM, and saves the cleaned text and structured intelligence back into MongoDB as `status: "processed"`.

---

## Status at a glance

| Step | Task | Status | Details |
|---|---|---|---|
| 1 | Connect to MongoDB & query `"new"` notices | ✅ Done | Queries `status: "new"` from `university_documents` |
| 2 | Automated PDF downloading | ✅ Done | Downloads via `requests` without manual file handling |
| 3 | OCR extraction on downloaded PDF | ✅ Done | Reuses `pdf2image` + `pytesseract` |
| 4 | OCR noise cleanup & normalization | ✅ Done | Fixes italic font time errors (`JJ` $\rightarrow$ `11 a.m.`) & trims crest logo noise |
| 5 | LLM structured extraction | ✅ Done | LangChain `prompt | model | parser` (`openai/gpt-oss-120b`) |
| 6 | Save extracted data into MongoDB | ✅ Done | Adds `raw_text`, `structured_data`, and `processed_at` via `$set` |
| 7 | Update document status | ✅ Done | Marks `status = "processed"` only upon complete success |
| 8 | Batch processing loop | ✅ Done | Iterates through all pending notices automatically |
| 9 | Fault tolerance & temp cleanup | ✅ Done | Per-notice `try/except/finally` ensures zero batch crashes and zero disk leaks |

---

## Architecture & Data Flow

```text
                        MongoDB
                           │
                           ▼
                 Find status == "new"
                           │
                           ▼
                    Notice PDF URL
                           │
                           ▼
               Download PDF to temp file
                           │
                           ▼
                     ocr.py (OCR)
            (pdf2image + pytesseract)
                           │
                           ▼
               clean_ocr_text() Filter
          - Discard top logo crest noise
          - Normalize OCR font glitches (JJ -> 11)
                           │
                           ▼
                   Cleaned Raw Text
                           │
                           ▼
               LangChain LLM Pipeline
         (Prompt + GPT-OSS-120B + JsonOutputParser)
                           │
                           ▼
                    Structured JSON
                           │
                           ▼
                 Save back to MongoDB
              ┌────────────┴────────────┐
              ▼                         ▼
         "raw_text"             "structured_data"
                           │
                           ▼
               "status" = "processed"
                           │
                           ▼
             Delete temporary PDF file
```

---

## Technical Investigations & Bugs Solved

### Bug 1: Why the LLM predicted "10 a.m." or "9 a.m." instead of "11 a.m."
- **Root Cause**: In MAKAUT notices, timings like *`between 11 a.m. to 4 p.m.`* are printed in an **italic serif font**. The slanted stems and curved serifs caused Tesseract OCR to misread `11` as `JJ`, `J/`, or `Il`.
- Because `JJ a.m.` is gibberish as a time expression, the LLM defaulted to its prior knowledge of typical Indian university reporting hours (**10 a.m.** or **9 a.m.**).
- **The Fix**:
  1. Added regex normalization in `clean_ocr_text()` to catch common OCR misreadings of numbers before `am`/`pm` (e.g. `JJ a.m.` $\rightarrow$ `11 a.m.`).
  2. Enhanced prompt instructions in `prompt.py` to inform the LLM that the source text is from OCR and may contain optical character substitutions.

### Bug 2: University Crest/Logo Noise at the top of notices
- **Root Cause**: MAKAUT notices feature the circular university crest at the top. Tesseract attempts to read the circular Bengali and English motto graphics, generating noise lines at the very start of the text:
  ```text
  oyna ams waa nan
  Min
  (eel
  MAULANA ABUL KALAM AZAD UNIVERSITY OF TECHNOLOGY, WEST BENGAL
  ```
- **The Fix**:
  - Implemented header pattern detection (`MAULANA ABUL KALAM AZAD UNIVERSITY`, `MAKAUT`, etc.) in `clean_ocr_text()`.
  - All lines preceding the official university header are sliced away, leaving a clean, professional document start.

### Bug 3: Temporary PDF Disk Bloat
- **Solution**: Handled with Python's `try ... finally` construct:
  ```python
  try:
      download_pdf(pdf_url, temp_pdf_path)
      docs = ocr_extract_pdf(temp_pdf_path)
      # ... LLM extraction ...
  finally:
      if os.path.exists(temp_pdf_path):
          os.remove(temp_pdf_path)
  ```
  The downloaded PDF exists only during OCR processing and is guaranteed to be deleted even if network, OCR, or LLM errors occur.

---

## MongoDB Document Structure

Every document in `university_documents` preserves its original Module 1 metadata while being enriched by Module 2:

```json
{
  "_id": "ObjectId(...)",
  "notice_id": "c701185f86386569cd6f34f6b5d033073f410a21f74847c3f8d4f954a7fe1b77",
  "title": "Notice Regarding the Maintenance of Campus Discipline and the Prohibition of Creating Disorder",
  "url": "https://makautwb.ac.in/datas/users/0-noti_bloking_unlocking26.pdf",
  "flagged_new_on_site": true,
  "detected_at": "2026-09-07T20:01:44.833Z",
  "status": "processed",
  "processed_at": "2026-09-17T12:26:55.964Z",

  "raw_text": "MAULANA ABUL KALAM AZAD UNIVERSITY OF TECHNOLOGY, WEST BENGAL\n...",

  "structured_data": {
    "notice_type": "Discipline",
    "title": "Prohibition of obstruction of ingress/egress, gate blocking, gherao and related acts",
    "reference_no": "MAKAUT/RE/Notice-106/317",
    "issue_date": "07-09-2026",
    "target_audience": "All university community including students, faculty, staff...",
    "important_dates": {
      "start_date": null,
      "last_date": null
    },
    "fees": {
      "amount": null,
      "currency": null
    },
    "action_required": "All members must refrain from blocking gates, wrongful restraint...",
    "key_points": [
      "Blocking, locking, chaining or obstructing any main gate is strictly prohibited.",
      "Gheraoing or physically blocking university officials is prohibited."
    ],
    "issued_by": "Dr. S. K. Maity, Registrar (Addl. Charge) & Inspector of Colleges",
    "summary": "The university has issued an immediate prohibition on any obstruction of gates..."
  }
}
```

---

## Core Files Overview

### 1. `ocr.py`
- Converts PDF pages into images using `pdf2image.convert_from_path()`.
- Extracts raw text using `pytesseract.image_to_string()`.
- Cleans and normalizes text with `clean_ocr_text()`:
  - Eliminates emblem/logo artifacts before the main header.
  - Normalizes OCR font errors (e.g. `JJ a.m.` $\rightarrow$ `11 a.m.`).
  - Removes short non-alphabetic noise strings.

### 2. `prompt.py`
- Defines the structured Pydantic/JSON target schema:
  `notice_type`, `title`, `reference_no`, `issue_date`, `target_audience`, `important_dates`, `fees`, `action_required`, `key_points`, `issued_by`, `summary`.
- Provides strict extraction rules (null handling, date formats, OCR tolerance).
- Employs LangChain's `JsonOutputParser` to parse output deterministically into a Python dictionary.

### 3. `main.py`
- Connects to MongoDB using `pymongo.MongoClient` and `.env`.
- Contains `download_pdf()` helper to stream PDFs to temporary storage.
- `process_new_notices(limit=None)` runs the batch pipeline:
  - Queries `status: "new"`.
  - Downloads $\rightarrow$ OCRs $\rightarrow$ LLM parses $\rightarrow$ MongoDB updates.
  - Catches exceptions per document to prevent pipeline interruptions.
  - Deletes temporary PDF files in `finally:`.

---

## How to Run

### 1. Activate Environment & Navigate
```bash
cd /Users/farhanakhtar/Desktop/Project/UniAi/Module2
```

### 2. Run Batch Processing
```bash
python3 main.py
```

### 3. Test/Process a Limited Batch
You can process a specific number of documents (e.g. 5 notices) via Python:
```python
from main import process_new_notices
process_new_notices(limit=5)
```

---

## Validation Checklist

- [x] MongoDB connection successful (`university_assistant.university_documents`).
- [x] Automatic PDF downloading via `requests` without browser overhead.
- [x] Temporary PDF files automatically removed (`temp_*.pdf`).
- [x] Logo noise at document header trimmed cleanly.
- [x] Font misreads (e.g. italic `11 a.m.`) corrected in OCR text.
- [x] LLM successfully extracts JSON matching the required schema.
- [x] MongoDB document updated via `{"$set": ...}` without losing Module 1 fields.
- [x] Document status changes from `"new"` to `"processed"`.
- [x] If processing fails on any notice, error is logged and notice remains `"new"`.
- [x] Next run only processes remaining `"new"` documents (idempotent).

---

## What's NOT Built Yet (Next Modules)

- ❌ **Module 3: Text Chunking & Preprocessing**: Splitting notice bodies and structured metadata into clean semantic chunks.
- ❌ **Module 4: Embedding Generation & Vector Database**: Storing chunk embeddings (e.g., ChromaDB / FAISS) for dense retrieval.
- ❌ **Module 5: RAG & User Query Interface**: Retrieving top-k chunks, grounding LLM answers, and handling student queries.

---

## One-sentence summary for your professor

> "Module 2 transforms raw university notice URLs into structured, query-ready intelligence by orchestrating an automated pipeline that downloads PDFs, cleans and normalizes OCR artifacts (including slanted-font misrecognitions and crest noise), extracts 10 core metadata dimensions via an open-weights LLM, and idempotently updates MongoDB documents with per-notice fault isolation."
