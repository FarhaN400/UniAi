
import os
import re
import tempfile
import hashlib
import requests

from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from pymongo import MongoClient, ReturnDocument

from ocr import extract_pdf_text, ocr_extract_pdf
from prompt import notice_extraction_prompt as prompt, parser
from schema import NoticeSchema


# =====================================================
# 1. CONFIGURATION
# =====================================================

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")

if not MONGO_URI:
    raise ValueError("MONGO_URI not found in .env")

client = MongoClient(MONGO_URI)
db = client["university_assistant"]
collection = db["university_documents"]

# GitHub Actions uses an external model; local development keeps Ollama.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
if LLM_PROVIDER == "groq":
    if not os.getenv("GROQ_API_KEY"):
        raise ValueError("GROQ_API_KEY required when LLM_PROVIDER=groq")
    from langchain_groq import ChatGroq
    MODEL_NAME = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
    llm = ChatGroq(model=MODEL_NAME, temperature=0, max_tokens=2048)
elif LLM_PROVIDER == "ollama":
    from langchain_ollama import ChatOllama
    MODEL_NAME = os.getenv("OLLAMA_MODEL", "qwen3:4b-instruct")
    llm = ChatOllama(model=MODEL_NAME, temperature=0, num_ctx=8192,
                     num_predict=2048, keep_alive="1m")
else:
    raise ValueError("LLM_PROVIDER must be 'ollama' or 'groq'")

SHORT_TEXT_LIMIT = 7000
CHUNK_SIZE = 2500
MAX_ATTEMPTS = max(1, int(os.getenv("SYNC_MAX_ATTEMPTS", "4")))
MAX_PDF_BYTES = 25 * 1024 * 1024
AUTO_APPROVE_LONG_NOTICES = os.getenv("AUTO_APPROVE_LONG_NOTICES", "0") == "1"

chain = prompt | llm | parser


# =====================================================
# 2. CUSTOM EXCEPTION
# =====================================================

class InvalidPDFError(ValueError):
    pass


# =====================================================
# 3. DOWNLOAD PDF
# =====================================================

def download_pdf(url, save_path):
    """Download a bounded PDF to a temporary file; always call cleanup afterwards."""
    from urllib.parse import urlsplit
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in {"makautwb.ac.in", "www.makautwb.ac.in"}:
        raise InvalidPDFError("Only official HTTPS MAKAUT PDF URLs are permitted")
    with requests.get(url, timeout=(10, 40), stream=True) as response:
        response.raise_for_status()
        total = 0
        with open(save_path, "wb") as file:
            for chunk in response.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_PDF_BYTES:
                    raise InvalidPDFError("PDF exceeds 25 MB limit")
                file.write(chunk)
    with open(save_path, "rb") as file:
        if file.read(5) != b"%PDF-":
            raise InvalidPDFError(f"Invalid PDF file: {url}")
    return save_path


def sha256_file(path):
    result = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            result.update(block)
    return result.hexdigest()

# =====================================================
# 4. STRUCTURED EXTRACTION + PYDANTIC
# =====================================================

def extract_structured_data(text):
    result = chain.invoke({
        "text": text
    })

    validated = NoticeSchema.model_validate(result)

    return validated.model_dump()


# =====================================================
# 5. SPLIT LONG TEXT INTO CHUNKS
# =====================================================

def split_text(text, max_chars=CHUNK_SIZE):
    """
    Prefer paragraph boundaries, then line boundaries.
    Hard-split only when an individual line is too long.

    No text is intentionally discarded.
    """

    chunks = []
    current = ""

    # Preserve paragraphs and section headings.
    paragraphs = re.split(r"\n\s*\n", text)

    for paragraph in paragraphs:
        paragraph = paragraph.strip()

        if not paragraph:
            continue

        # Break oversized paragraphs along lines.
        if len(paragraph) > max_chars:
            parts = paragraph.splitlines()
        else:
            parts = [paragraph]

        for part in parts:
            part = part.strip()

            if not part:
                continue

            # Handle extremely long lines.
            while len(part) > max_chars:
                if current:
                    chunks.append(current)
                    current = ""

                chunks.append(part[:max_chars])
                part = part[max_chars:]

            if not part:
                continue

            separator = "\n" if current else ""

            if len(current) + len(separator) + len(part) <= max_chars:
                current += separator + part
            else:
                if current:
                    chunks.append(current)

                current = part

    if current:
        chunks.append(current)

    return chunks


# =====================================================
# 6. MERGE CHUNK EXTRACTIONS
# =====================================================

def merge_chunk_results(results):
    """
    Deterministic merge.

    Important:
    - Preserve unique key points from every chunk.
    - Avoid inventing one deadline from conflicting dates.
    - Avoid inventing one fee from multiple monetary values.
    - Keep chunk outputs separately for factual review.
    """

    if not results:
        raise ValueError("No chunk results to merge")

    merged = {
        "notice_type": "General",
        "title": None,
        "reference_no": None,
        "issue_date": None,
        "target_audience": None,
        "important_dates": {
            "start_date": None,
            "last_date": None
        },
        "fees": {
            "amount": None,
            "currency": None
        },
        "action_required": None,
        "key_points": [],
        "issued_by": None,
        "summary": None
    }

    # Prefer information from the document header
    # for reference number, date and subject.
    first = results[0]

    merged["notice_type"] = first.get(
        "notice_type", "General"
    )

    merged["title"] = first.get("title") or "University Notice"

    for field in ["reference_no", "issue_date"]:
        merged[field] = next(
            (
                item[field]
                for item in results
                if item.get(field) is not None
            ),
            None
        )

    # Prefer the first non-null audience and category.
    merged["target_audience"] = next(
        (
            item["target_audience"]
            for item in results
            if item.get("target_audience")
        ),
        None
    )

    if merged["notice_type"] == "General":
        merged["notice_type"] = next(
            (
                item["notice_type"]
                for item in results
                if item.get("notice_type") != "General"
            ),
            "General"
        )

    # Use the last non-null signing authority.
    merged["issued_by"] = next(
        (
            item["issued_by"]
            for item in reversed(results)
            if item.get("issued_by")
        ),
        None
    )

    # Keep all distinct material key points.
    seen = set()

    def add_point(point):
        if not isinstance(point, str):
            return

        point = point.strip()
        key = " ".join(point.lower().split())

        if point and key not in seen:
            merged["key_points"].append(point)
            seen.add(key)

    for item in results:
        for point in item.get("key_points", []):
            add_point(point)

    # Preserve action-required information from all chunks.
    actions = []

    for item in results:
        action = item.get("action_required")

        if action and action not in actions:
            actions.append(action)

    merged["action_required"] = (
        " ".join(actions) if actions else None
    )

    # Dates: never arbitrarily select a conflicting value.
    for field in ["start_date", "last_date"]:
        values = list(dict.fromkeys(
            item.get("important_dates", {}).get(field)
            for item in results
            if item.get("important_dates", {}).get(field)
        ))

        if len(values) == 1:
            merged["important_dates"][field] = values[0]

        elif len(values) > 1:
            add_point(
                f"Extracted {field} candidates requiring "
                f"verification: {', '.join(values)}."
            )

    # Fee fields: select only when one consistent
    # amount/currency pair is found.
    fee_values = []

    for item in results:
        fee = item.get("fees", {})

        if fee and fee.get("amount") is not None:
            value = (
                str(fee["amount"]),
                fee.get("currency")
            )

            if value not in fee_values:
                fee_values.append(value)

    if len(fee_values) == 1:
        merged["fees"] = {
            "amount": fee_values[0][0],
            "currency": fee_values[0][1]
        }

    elif len(fee_values) > 1:
        add_point(
            "Multiple monetary values require verification: "
            + "; ".join(
                f"{amount} {currency or ''}"
                for amount, currency in fee_values
            )
        )

    # Build a summary from chunk summaries.
    # This is a provisional long-document summary.
    summaries = [
        item["summary"].strip()
        for item in results
        if item.get("summary")
    ]

    merged["summary"] = (
        " ".join(summaries)
        if summaries
        else "University notice requiring review."
    )

    validated = NoticeSchema.model_validate(merged)

    return validated.model_dump()


# =====================================================
# 7. PROCESS LONG NOTICE
# =====================================================

def process_long_notice(raw_text):
    chunks = split_text(raw_text)

    print(f"  -> Long notice detected")
    print(f"  -> Total chunks: {len(chunks)}")

    results = []

    for index, chunk in enumerate(chunks, start=1):
        print(
            f"  -> Extracting chunk "
            f"{index}/{len(chunks)} "
            f"({len(chunk)} characters)"
        )

        # Same extraction prompt and schema.
        data = extract_structured_data(chunk)
        results.append(data)

    merged = merge_chunk_results(results)

    print("  -> All chunks extracted")
    print("  -> Merged JSON validated")

    return merged, results


# =====================================================
# 8. MAIN BATCH PIPELINE
# =====================================================

def _eligible_processing_query(now):
    """Pending, due for retry, or abandoned processing leases."""
    return {"$or": [
        {"status": "new", "processing_attempts": {"$lt": MAX_ATTEMPTS}},
        {"status": "new", "processing_attempts": {"$exists": False}},
        {"status": "failed", "processing_attempts": {"$lt": MAX_ATTEMPTS},
         "next_retry_at": {"$lte": now}},
        {"status": "processing", "processing_started_at": {
            "$lt": now - timedelta(hours=1)}, "processing_attempts": {"$lt": MAX_ATTEMPTS}},
    ]}


def _extract_notice_text(pdf_path):
    """Try native PDF text first; use OCR when that returns no usable text."""
    try:
        text = extract_pdf_text(pdf_path)
    except Exception as exc:
        print(f"  -> Direct extraction unavailable: {exc}; trying OCR")
        text = None
    if not isinstance(text, str) or not text.strip():
        text = ocr_extract_pdf(pdf_path)
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Both PDF text extraction and OCR returned empty text")
    return text


def _record_processing_failure(notice, error):
    attempt = int(notice.get("processing_attempts") or 1)
    delay_minutes = min(15 * (2 ** max(attempt - 1, 0)), 480)
    collection.update_one(
        {"_id": notice["_id"], "status": "processing"},
        {"$set": {
            "status": "failed", "processing_error": str(error)[:1500],
            "last_failed_at": datetime.now(timezone.utc),
            "next_retry_at": datetime.now(timezone.utc) + timedelta(minutes=delay_minutes),
        }, "$unset": {"processing_started_at": ""}},
    )
    print(f"  -> FAILED attempt {attempt}/{MAX_ATTEMPTS}: {error}")


def process_new_notices(limit=None):
    """Claim and process new/retryable notices; return a machine-readable report.

    A crash does not strand a notice indefinitely: the hour-old lease is
    automatically eligible for a retry. The indexer runs independently after.
    """
    limit = int(limit if limit is not None else os.getenv("SYNC_PROCESS_LIMIT", "3"))
    if limit < 0:
        raise ValueError("limit must be nonnegative")
    report = {"selected": 0, "processed": 0, "review_required": 0,
              "failed": 0, "invalid": 0}

    for _ in range(limit):
        now = datetime.now(timezone.utc)
        notice = collection.find_one_and_update(
            _eligible_processing_query(now),
            {"$set": {"status": "processing", "processing_started_at": now},
             "$inc": {"processing_attempts": 1}},
            sort=[("detected_at", 1)], return_document=ReturnDocument.AFTER,
        )
        if not notice:
            break

        report["selected"] += 1
        pdf_path = None
        try:
            if not notice.get("notice_id") or not notice.get("url"):
                raise ValueError("Missing notice_id or URL")
            print(f"[Module2] Processing {notice.get('title', 'Untitled Notice')}")
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                pdf_path = tmp.name
            download_pdf(notice["url"], pdf_path)
            pdf_digest = sha256_file(pdf_path)
            raw_text = _extract_notice_text(pdf_path)
            is_long = len(raw_text) > SHORT_TEXT_LIMIT
            if is_long:
                structured_data, chunk_results = process_long_notice(raw_text)
            else:
                structured_data = extract_structured_data(raw_text)
                chunk_results = None

            # Default: potentially incomplete/contradictory long-document
            # merges remain out of the search index until a manual review.
            needs_review = bool(is_long and not AUTO_APPROVE_LONG_NOTICES)
            if is_long and AUTO_APPROVE_LONG_NOTICES:
                points = structured_data.get("key_points") or []
                needs_review = any(
                    "requiring verification" in str(p).lower() or
                    "require verification" in str(p).lower()
                    for p in points
                )

            now = datetime.now(timezone.utc)
            update_fields = {
                "raw_text": raw_text, "structured_data": structured_data,
                "pdf_sha256": pdf_digest, "last_content_checked_at": now,
                "processed_at": now, "extraction_model": MODEL_NAME,
                "requires_chunking": is_long,
                "status": "review_required" if needs_review else "processed",
                "quality_review_required": needs_review,
                "pinecone_indexed": False,
            }
            if is_long:
                update_fields["chunk_extractions"] = chunk_results
            updated = collection.update_one(
                {"_id": notice["_id"], "status": "processing"},
                {"$set": update_fields,
                 "$unset": {"processing_error": "", "next_retry_at": "",
                            "processing_started_at": "", "invalid_pdf_url": ""}},
            )
            if updated.matched_count != 1:
                raise RuntimeError("Notice lease lost before saving extraction")
            report["review_required" if needs_review else "processed"] += 1
            print("  -> Review required" if needs_review else "  -> Processed; ready for indexing")
        except InvalidPDFError as error:
            # A PDF may be unavailable temporarily while MAKAUT is uploading it.
            # Retry a few times before permanently quarantining the URL.
            if int(notice.get("processing_attempts") or 0) < MAX_ATTEMPTS:
                report["failed"] += 1
                _record_processing_failure(notice, error)
            else:
                report["invalid"] += 1
                collection.update_one(
                    {"_id": notice["_id"], "status": "processing"},
                    {"$set": {"status": "invalid", "processing_error": str(error),
                              "invalid_pdf_url": notice.get("url")},
                     "$unset": {"processing_started_at": ""}},
                )
                print(f"  -> INVALID after {MAX_ATTEMPTS} attempts: {error}")
        except Exception as error:
            report["failed"] += 1
            _record_processing_failure(notice, error)
        finally:
            if pdf_path and os.path.exists(pdf_path):
                os.remove(pdf_path)

    print(f"[Module2] {report}")
    return report


if __name__ == "__main__":
    try:
        process_new_notices(limit=2)
    finally:
        client.close()
