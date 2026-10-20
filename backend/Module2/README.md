# 📄 Module 2 — Document Processing & Structured Intelligence Extraction

> **University AI Assistant (UniAI) — MAKAUT**  
> Automated PDF acquisition, dual text extraction (digital extraction + high-resolution OCR), Pydantic V2 schema validation, dual LLM provider support (Ollama & Groq), and deterministic chunk merging with fault tolerance.

Module 2 transforms raw university notices pulled by **Module 1** into clean, machine-searchable, structured JSON intelligence. It pulls pending circulars (`status: "new"`) from MongoDB, downloads and verifies the official PDF files, cleans optical character recognition (OCR) artifacts, segments long notices into chunks, extracts structured entities using **Qwen 3 4B-Instruct** (via Ollama) or **GPT / Llama models** (via Groq), validates outputs against strict Pydantic schemas, and persists the extracted intelligence back into MongoDB.

---

## 🎯 Key Objectives

1. **Automated End-to-End Pipeline:** Continuously pulls new circulars from MongoDB, streams PDFs to temporary storage with magic-byte validation (`%PDF-`), and safely cleans up disk space in `finally:` blocks.
2. **Dual-Path Text Extraction (`ocr.py`):**
   - **Direct Digital Text Extraction (`extract_pdf_text`):** Attempts native digital extraction via `pypdf.PdfReader` first (instant, 100% accurate, no image conversion overhead).
   - **High-Res OCR Fallback (`ocr_extract_pdf`):** If the PDF is scanned or yields insufficient text (< 80 characters), automatically renders pages at 300 DPI, converts to grayscale, applies 1.5x contrast enhancement, and reads via Tesseract OCR (`--oem 3 --psm 6`).
3. **Advanced Optical Noise Normalization:** Regex cleaning removes university crest artifacts, repairs spurious spaces in dates (`01.1 0.2026` $\rightarrow$ `01.10.2026`), and fixes slanted font misreads (`JJ a.m.` $\rightarrow$ `11 a.m.`).
4. **Strict Pydantic Contract (`schema.py`):** Enforces 10 structured dimensions (`ConfigDict(extra="forbid")`) with field validators to eliminate hallucinated fields or malformed data types.
5. **Intelligent Chunking for Long Circulars:** Automatically detects long notices (> 7,000 characters), segments them along paragraph boundaries (`CHUNK_SIZE = 2,500`), extracts information per chunk, and merges results deterministically.
6. **Dual LLM Provider Support:** Seamlessly switches between local execution (**Ollama** with `qwen3:4b-instruct`) and cloud inference (**Groq** with `openai/gpt-oss-20b` or custom models).
7. **Fault-Tolerant Lease Management:** Uses atomic lease claiming (`find_one_and_update`), 1-hour lease expiration for crash recovery, exponential backoff retries, and quarantine to `status: "invalid"` after exhausting configured attempts.

---

## 🏗️ Architecture & Processing Workflow

```text
                       MongoDB: university_documents
                                     │
                                     ▼
                    Atomic Lease Claim (_eligible_processing_query)
                       - status: "new" OR retryable "failed"
                       - status set to "processing" with timestamp
                                     │
                                     ▼
                            Download PDF to Temp
                          Validate Magic Bytes (%PDF-)
                                     │
                    ┌────────────────┴────────────────┐
                    ▼                                 ▼
             Valid PDF File                     Invalid PDF File
                    │                        - Retry with backoff
                    ▼                        - If attempts >= 4:
           Dual-Path Text Extraction           status: "invalid"
                    │                        - invalid_pdf_url
          ┌─────────┴─────────┐
          ▼                   ▼
    Digital PDF         Scanned PDF
  (pypdf.PdfReader)   (300 DPI + Contrast
  Instant extraction    + Tesseract PSM 6)
          │                   │
          └─────────┬─────────┘
                    ▼
          clean_ocr_text() Normalization
          - Slanted font repair (JJ -> 11)
          - Date spacing correction
          - Logo noise trimming
                    │
                    ▼
            Clean Document Text
                    │
         ┌──────────┴──────────┐
         ▼                     ▼
    Short Notice          Long Notice
  (<= 7,000 chars)     (> 7,000 chars)
         │                     │
         │                     ▼
         │             split_text(2,500 chars)
         │                     │
         │                     ▼
         │           Per-Chunk LLM Extraction
         │                     │
         │                     ▼
         │             merge_chunk_results()
         │                     │
         └──────────┬──────────┘
                    ▼
     Structured Extraction Pipeline
   (Prompt + LLM [Ollama/Groq] + JsonOutputParser)
                    │
                    ▼
       Pydantic Schema Validation
     (NoticeSchema.model_validate)
                    │
                    ▼
           Update MongoDB Document
         ┌──────────┴──────────┐
         ▼                     ▼
    Short Notice          Long Notice
  - status: "processed" - status: "review_required"
  - structured_data     - quality_review: true
  - pinecone_indexed: F   (or auto-approved if clean)
                        - chunk_extractions
                    │
                    ▼
       Delete Temporary PDF File (finally:)
```

---

## 🔍 Dual-Path Text Extraction & OCR Normalization (`ocr.py`)

MAKAUT circulars range from digitally authored PDFs to low-resolution photocopies. Module 2 handles both efficiently:

### 1. Direct PDF Extraction with OCR Fallback
```python
def extract_pdf_text(pdf_path):
    """Attempt direct digital extraction first; fallback to OCR if scanned."""
    try:
        reader = PdfReader(pdf_path)
        extracted = [page.extract_text() for page in reader.pages if page.extract_text()]
        direct_text = "\n".join(extracted).strip()
        if len(direct_text) > 80:
            return clean_ocr_text(direct_text)
    except Exception:
        pass
    return ocr_extract_pdf(pdf_path)
```

### 2. High-Resolution OCR Pipeline (`ocr_extract_pdf`)
When scanned documents are detected:
```python
images = convert_from_path(pdf_path, dpi=300)
for img in images:
    gray_img = ImageOps.grayscale(img)
    enhanced_img = ImageEnhance.Contrast(gray_img).enhance(1.5)
    text = pytesseract.image_to_string(enhanced_img, config="--oem 3 --psm 6")
```
- **300 DPI Rendering:** Resolves fine print, small table numbers, and reference numbers.
- **Grayscale + 1.5x Contrast:** Strips background discoloration and paper stains.
- **PSM 6 (Single Uniform Block):** Optimized for structured academic notifications and tabular dates.

### 3. Optical Noise & Regex Normalization (`clean_ocr_text`)
- **Slanted-Font Time Corrections:** In circulars typeset with slanted serif fonts, `11` is frequently misread as `JJ`, `J/`, `Il`, or `ll`. Normalized via `(?i)\b(JJ|J/|J\]|Il|1l|II|ll)\s*([ap]\.?m\.?)` $\rightarrow$ `11 \2`.
- **Date Spacing Glitches:** Repairs spaces inserted into dates (`01.1 0.2026` $\rightarrow$ `01.10.2026`).
- **University Crest Artifacts:** Trims noise lines generated by the university logo emblem appearing above the main header (`MAULANA ABUL KALAM AZAD UNIVERSITY...`).
- **Line Preservation:** Preserves numbered points, short dates, and fee figures rather than discarding short lines indiscriminately.

---

## 📐 Pydantic Data Contract (`schema.py`)

Extraction outputs are validated against strict Pydantic V2 schemas before database storage:

```python
class ImportantDates(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_date: Optional[str]
    last_date: Optional[str]

class Fees(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: Optional[str] = None
    currency: Optional[str] = None

    @field_validator("amount", mode="before")
    @classmethod
    def normalize_amount(cls, value):
        if value is None:
            return None
        if isinstance(value, bool):
            raise ValueError("Fee amount cannot be boolean")
        if isinstance(value, (int, float, str)):
            return str(value)
        raise ValueError("Invalid fee amount")

class NoticeSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notice_type: Literal[
        "Examination", "Admission", "Scholarship",
        "Discipline", "Administrative", "Academic Calendar", "General"
    ]
    title: str
    reference_no: Optional[str]
    issue_date: Optional[str]
    target_audience: Optional[str]
    important_dates: ImportantDates
    fees: Fees
    action_required: Optional[str]
    key_points: List[str]
    issued_by: Optional[str]
    summary: str
```

- **`extra="forbid"`:** Disallows hallucinated fields outside the university contract.
- **7-Type Categorization:** Categorizes circulars into standardized types (`Examination`, `Admission`, `Scholarship`, etc.).
- **Sub-Object Guarantees:** Ensures `fees` and `important_dates` are always structured sub-dictionaries, even when specific values are `null`.

---

## 🧩 Intelligent Chunking & Deterministic Merging (`main.py`)

When circulars exceed `SHORT_TEXT_LIMIT = 7000` characters:
1. **Paragraph-Preserving Splitting (`split_text`):** Breaks text into chunks of at most 2,500 characters, respecting paragraph boundaries (`\n\n`) and line breaks.
2. **Chunk Extraction:** Each chunk is extracted independently through the LLM.
3. **Deterministic Merging (`merge_chunk_results`):**
   - **Header Details:** Prioritizes reference number, issue date, and notice type from the initial chunk.
   - **Issuing Authority:** Extracts signing authority from the trailing chunk.
   - **Key Points & Actions:** Aggregates unique key points and action directives across all chunks.
   - **Conflict Detection:** When chunks report conflicting dates or multiple fee amounts, the merger records candidate values in `key_points` for human verification rather than arbitrarily picking one.
   - **Quality Control:** By default, saves the document as `status: "review_required"`, sets `quality_review_required: True`, and stores raw chunk outputs in `chunk_extractions`. If `AUTO_APPROVE_LONG_NOTICES=1` is set, notices without conflict warnings are approved automatically.

---

## 🛡️ Robust Lease Management & Retry Mechanism

Module 2 includes production-grade lease locking for batch and automated environments:
- **Atomic Document Lease (`find_one_and_update`):** Atomically claims an eligible document by setting `status: "processing"` and `processing_started_at`.
- **Stale Lease Recovery:** Documents left in `"processing"` state for over 1 hour (e.g., due to an unexpected process crash) are automatically reclaimed for retry.
- **Exponential Backoff:** Failed attempts delay subsequent retries with doubling delays: `delay = min(15 * 2^(attempt - 1), 480)` minutes.
- **Quarantine:** After reaching `MAX_ATTEMPTS` (default 4, configurable via `SYNC_MAX_ATTEMPTS`), the circular is marked `status: "invalid"` with detailed diagnostics, preventing pipeline stalls.

---

## 🗄️ MongoDB Document Schema

Following Module 2 processing, notices in the `university_documents` collection contain:

```json
{
  "_id": "ObjectId(...)",
  "notice_id": "c701185f86386569cd6f34f6b5d033073f410a21f74847c3f8d4f954a7fe1b77",
  "title": "Notice Regarding Semester Examination Form Fill-up 2026",
  "url": "https://makautwb.ac.in/datas/users/0-exam_form_2026.pdf",
  "pdf_sha256": "3e9b1d75f284e9b8c...",
  "flagged_new_on_site": true,
  "detected_at": "2026-09-07T20:01:44.833Z",
  "status": "processed",
  "processed_at": "2026-09-17T12:26:55.964Z",
  "last_content_checked_at": "2026-09-17T12:26:55.964Z",
  "extraction_model": "qwen3:4b-instruct",
  "requires_chunking": false,
  "quality_review_required": false,
  "pinecone_indexed": false,
  "raw_text": "MAULANA ABUL KALAM AZAD UNIVERSITY OF TECHNOLOGY...",
  "structured_data": {
    "notice_type": "Examination",
    "title": "Notice Regarding Semester Examination Form Fill-up 2026",
    "reference_no": "COE/MAKAUT/2026/089",
    "issue_date": "15-09-2026",
    "target_audience": "All eligible undergraduate and postgraduate students",
    "important_dates": {
      "start_date": "16-09-2026",
      "last_date": "30-09-2026"
    },
    "fees": {
      "amount": "1200",
      "currency": "INR"
    },
    "action_required": "Submit exam form online and pay fee before deadline.",
    "key_points": [
      "Online portal opens on 16 September 2026.",
      "Last date of submission without late fine is 30 September 2026.",
      "Admit cards will be available 3 days prior to commencement."
    ],
    "issued_by": "Controller of Examinations",
    "summary": "Official notification regarding online examination form submission and fee payment for upcoming semester examinations."
  }
}
```

---

## 📂 Source Code Files

| File | Description |
|---|---|
| [`main.py`](main.py) | **Batch Pipeline Orchestrator:** PDF downloader, magic-byte check, chunking engine, chunk merger, MongoDB updater, lease manager, and batch reporter. |
| [`ocr.py`](ocr.py) | **Dual Extraction & OCR Normalization:** Direct PyPDF extraction, 300 DPI Tesseract OCR fallback, font slant corrections (`JJ` $\rightarrow$ `11`), date spaces, and crest trimming. |
| [`schema.py`](schema.py) | **Pydantic Validation Models:** `NoticeSchema`, `ImportantDates`, and `Fees` strict data models. |
| [`prompt.py`](prompt.py) | **Prompt Engineering:** Strict extraction instructions, JSON output parser, and field constraint definitions. |
| [`README.md`](README.md) | Module 2 technical documentation and architecture guide. |

---

## ⚙️ Environment Configuration

Set the following variables in your root `.env` file:

```env
# MongoDB Atlas
MONGO_URI=mongodb+srv://<username>:<password>@cluster0.mongodb.net/?retryWrites=true&w=majority

# LLM Provider Selection: "ollama" (default local) or "groq" (cloud)
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen3:4b-instruct

# Optional: Groq Cloud Configuration
# LLM_PROVIDER=groq
# GROQ_API_KEY=gsk_...
# GROQ_MODEL=openai/gpt-oss-20b

# Pipeline Tuning (Optional)
SYNC_PROCESS_LIMIT=3
SYNC_MAX_ATTEMPTS=4
AUTO_APPROVE_LONG_NOTICES=0
```

---

## ▶️ How to Run

### 1. Start Ollama (When using Local LLM)

```bash
ollama run qwen3:4b-instruct
```

### 2. Run Batch Processing from Project Root

```bash
python3 backend/Module2/main.py
```

### 3. Programmatic Invocation

```python
from backend.Module2.main import process_new_notices

# Process up to 5 notices
report = process_new_notices(limit=5)
print(report)  # {'selected': 5, 'processed': 4, 'review_required': 1, 'failed': 0, 'invalid': 0}
```

---

## ✅ Validation Checklist

- [x] Downloads PDF files securely to temporary storage with magic-byte validation (`%PDF-`).
- [x] Enforces 25 MB file size limit and deletes temporary files in `finally:` blocks.
- [x] Direct digital PDF text extraction via `pypdf` avoids unnecessary OCR overhead.
- [x] 300 DPI Tesseract OCR fallback handles scanned circulars with contrast enhancement (1.5x).
- [x] OCR font slant errors (`JJ a.m.` $\rightarrow$ `11 a.m.`) corrected cleanly.
- [x] Spaces accidentally introduced into dates (`01.1 0.2026`) repaired by regex.
- [x] University crest and emblem artifacts trimmed above document headers.
- [x] Pydantic models validate JSON structure and forbid hallucinated fields.
- [x] Long documents (> 7,000 characters) chunked and merged deterministically.
- [x] Dual LLM provider support: Ollama (local) and Groq (cloud).
- [x] Fault-tolerant atomic lease claiming and exponential backoff retry logic.
