# 📄 Module 2 — Document Processing & Structured Extraction

> **University AI Assistant (UniAI) — MAKAUT**  
> Automated PDF acquisition, high-fidelity OCR enhancement, Pydantic schema validation, and LLM-powered structured intelligence extraction with chunking and fault tolerance.

Module 2 transforms raw university notices scraped in Module 1 into clean, machine-searchable structured JSON. It pulls unprocessed notices (`status: "new"`) from MongoDB, downloads and verifies the official PDF files, cleans optical character recognition (OCR) artifacts, splits long circulars into chunks, extracts structured entities using **Qwen 3 4B-Instruct** (via Ollama), validates outputs against strict Pydantic schemas, and persists the extracted intelligence back into MongoDB.

---

## 🎯 Key Objectives

1. **Automated End-to-End Pipeline:** Eliminates manual document inspection by continuously pulling new notices from MongoDB, streaming PDFs to temporary storage, and cleaning up disk space automatically.
2. **Enhanced OCR Pipeline:** Renders PDF pages at 300 DPI with grayscale conversion, contrast enhancement, layout segmentation, and regex corrections for font slant and date spacing errors.
3. **Strict Structured Extraction:** Maps free-form circulars into a deterministic JSON schema featuring 10 core dimensions: notice type, title, reference number, issue date, target audience, important dates, fees, required actions, key points, and issuing authority.
4. **Pydantic Validation (`schema.py`):** Enforces strict data models (`ConfigDict(extra="forbid")`) with custom field validators to eliminate hallucinated fields or malformed data types.
5. **Intelligent Chunking for Long Circulars:** Automatically detects long notices (> 7,000 characters), segments them along paragraph boundaries (`CHUNK_SIZE = 2,500`), extracts information per chunk, and merges results deterministically.
6. **Multi-State Quality Tracking:** Categorizes documents into `processed`, `review_required` (for long notices requiring human inspection), `invalid` (for non-PDF or corrupt links), or `new` (upon retryable failures).

---

## 🏗️ Architecture & Processing Workflow

```text
                       MongoDB: university_documents
                                     │
                                     ▼
                          Find status == "new"
                                     │
                                     ▼
                           Download PDF to Temp
                         Validate Magic Bytes (%PDF-)
                                     │
                    ┌────────────────┴────────────────┐
                    ▼                                 ▼
             Valid PDF File                     Invalid PDF File
                    │                        - status: "invalid"
                    ▼                        - processing_error
            ocr.py (High-Res OCR)            - invalid_pdf_url
          - Render at 300 DPI
          - Grayscale + Contrast (1.5x)
          - Tesseract (--oem 3 --psm 6)
          - clean_ocr_text() Normalization
                    │
                    ▼
            Cleaned Document Text
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
   (Prompt + Qwen 3 4B-Instruct + Parser)
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
  - quality_review: false - quality_review: true
  - structured_data     - chunk_extractions
                        - pinecone_indexed: false
                    │
                    ▼
       Delete Temporary PDF File (finally)
```

---

## 🔍 OCR Improvements & Normalization (`ocr.py`)

MAKAUT circulars frequently contain low-resolution scans, italicized fonts, and complex emblems that challenge standard OCR:

### 1. Preprocessing & Image Enhancement
```python
images = convert_from_path(pdf_path, dpi=300)
for img in images:
    gray_img = ImageOps.grayscale(img)
    enhanced_img = ImageEnhance.Contrast(gray_img).enhance(1.5)
    text = pytesseract.image_to_string(enhanced_img, config="--oem 3 --psm 6")
```
- **300 DPI Rendering:** Significantly improves recognition of fine print, fractions, and academic reference numbers.
- **Grayscale + 1.5x Contrast:** Eliminates paper discoloration and faint background artifacts.
- **PSM 6 (Single Uniform Block):** Improves column and tabular line reading over standard page segmentation.

### 2. Optical Noise & Font Correction (`clean_ocr_text`)
- **Slanted-Font Time Corrections:** In MAKAUT notices, timings like *"between 11 a.m. to 4 p.m."* are often typeset in slanted serif fonts where `11` is misread as `JJ`, `J/`, or `Il`. Regex patterns normalize `(JJ|J/|J\]|Il|1l|II|ll) a.m.` $\rightarrow$ `11 a.m.`.
- **Date Spacing Glitches:** OCR engines occasionally insert spurious spaces inside dates (e.g. `01.1 0.2026` $\rightarrow$ `01.10.2026`). Regex normalizes these into valid date strings.
- **University Logo Noise Removal:** Trims noise lines generated from circular university emblems (e.g., `oyna ams waa nan`, `(eel`) that appear above the official header (`MAULANA ABUL KALAM AZAD UNIVERSITY...`).
- **Short-Line Preservation:** Preserves numbered points, short dates, and numerical values while filtering out isolated non-alphabetic artifacts.

---

## 📐 Pydantic Data Contract (`schema.py`)

To ensure data integrity, extraction outputs are strictly validated by Pydantic models before being stored in MongoDB:

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
- **Type Literal for `notice_type`:** Standardizes classification across 7 strict categories.
- **Mandatory Sub-Objects:** Guarantees `fees` and `important_dates` are always dictionaries with required keys, even if their internal values are `null`.

---

## 🧩 Long Notice Handling & Chunk Merging (`main.py`)

When circulars exceed `SHORT_TEXT_LIMIT = 7000` characters:
1. **Paragraph-Preserving Splitting (`split_text`):** Breaks text into chunks of at most 2,500 characters, respecting paragraph boundaries (`\n\n`) and line breaks.
2. **Chunk Extraction:** Each chunk is extracted independently through the LLM.
3. **Deterministic Merging (`merge_chunk_results`):**
   - **Header Details:** Prioritizes reference number, issue date, and notice type from the initial chunk.
   - **Issuing Authority:** Extracts signing authority from the trailing chunk.
   - **Key Points & Actions:** Aggregates unique key points and action directives across all chunks.
   - **Conflict Detection:** When chunks report conflicting dates or multiple fee amounts, the merger records candidate values in `key_points` for human verification rather than arbitrarily picking one.
   - **Status:** Saves the document as `status: "review_required"`, sets `quality_review_required: True`, and stores raw chunk outputs in `chunk_extractions`.

---

## 🗄️ MongoDB Document Schema

Following Module 2 processing, notices in the `university_documents` collection contain:

```json
{
  "_id": "ObjectId(...)",
  "notice_id": "c701185f86386569cd6f34f6b5d033073f410a21f74847c3f8d4f954a7fe1b77",
  "title": "Notice Regarding Semester Examination Form Fill-up 2026",
  "url": "https://makautwb.ac.in/datas/users/0-exam_form_2026.pdf",
  "flagged_new_on_site": true,
  "detected_at": "2026-09-07T20:01:44.833Z",
  "status": "processed",
  "processed_at": "2026-09-17T12:26:55.964Z",
  "extraction_model": "qwen3:4b-instruct",
  "requires_chunking": false,
  "quality_review_required": false,
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

## 📂 File Structure

| File | Description |
|---|---|
| [`main.py`](file:///Users/farhanakhtar/Desktop/Project/UniAi/Module2/main.py) | **Batch Pipeline Orchestrator:** PDF downloader, magic byte validator, chunking engine, chunk merger, MongoDB updater, and summary reporter. |
| [`ocr.py`](file:///Users/farhanakhtar/Desktop/Project/UniAi/Module2/ocr.py) | **OCR Preprocessing & Normalization:** 300 DPI conversion, contrast enhancement, font slant corrections (`JJ` $\rightarrow$ `11`), date normalization, and logo noise trimming. |
| [`schema.py`](file:///Users/farhanakhtar/Desktop/Project/UniAi/Module2/schema.py) | **Pydantic Validation Models:** `NoticeSchema`, `ImportantDates`, and `Fees` models with strict validation rules. |
| [`prompt.py`](file:///Users/farhanakhtar/Desktop/Project/UniAi/Module2/prompt.py) | **Prompt Engineering:** Extraction guidelines, OCR tolerance rules, classification constraints, and LangChain `JsonOutputParser`. |
| `README.md` | Comprehensive module documentation and guide. |

---

## ⚙️ Environment Configuration

Module 2 requires a MongoDB connection string in the root `.env` file:

```env
MONGO_URI=mongodb+srv://<username>:<password>@cluster0.mongodb.net/?retryWrites=true&w=majority
```

### Local LLM Requirement (Ollama)
Module 2 uses **Qwen 3 4B-Instruct** running locally via Ollama:

```bash
# Verify Ollama is running and pull the model
ollama run qwen3:4b-instruct
```

---

## ▶️ How to Run

### 1. Run Batch Processing

```bash
cd /Users/farhanakhtar/Desktop/Project/UniAi/Module2
python3 main.py
```

### 2. Process a Limited Batch for Testing
You can control the batch size in `main.py` or invoke it directly:

```python
from main import process_new_notices
process_new_notices(limit=2)
```

### 3. Example Batch Summary Output

```text
============================================================
UniAI Module 2 | Batch Summary
============================================================
Total checked   : 10
Processed       : 8
Review required : 1
Failed          : 0
Invalid PDFs    : 1
============================================================
```

---

## ✅ Validation Checklist

- [x] Downloads PDF files securely to temporary storage with magic byte validation (`%PDF-`).
- [x] Automatically deletes temporary PDF files in `finally:` block, preventing disk bloat.
- [x] 300 DPI rendering + contrast enhancement improves small font extraction.
- [x] OCR font slant errors (`JJ a.m.` $\rightarrow$ `11 a.m.`) normalized cleanly.
- [x] Spaces accidentally introduced into dates (`01.1 0.2026`) repaired by regex.
- [x] University crest and emblem artifacts trimmed above document headers.
- [x] Pydantic models validate JSON structure and disallow extra keys.
- [x] Long documents (> 7,000 characters) chunked and merged deterministically.
- [x] Merged conflicts in dates/fees recorded for human verification.
- [x] Documents marked with appropriate lifecycle status (`processed`, `review_required`, `invalid`).
- [x] Batch processing runs with per-document fault tolerance, preventing entire batch crashes.
