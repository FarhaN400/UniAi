
import os
import re
import tempfile
import requests

from datetime import datetime, timezone
from dotenv import load_dotenv
from pymongo import MongoClient
from langchain_ollama import ChatOllama

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

MODEL_NAME = "qwen3:4b-instruct"

# Approximate character thresholds, not token counts.
SHORT_TEXT_LIMIT = 7000
CHUNK_SIZE = 2500

# Keep the context reasonably small for an 8 GB Mac.
llm = ChatOllama(
    model=MODEL_NAME,
    temperature=0,
    num_ctx=4096,
    num_predict=1600,
    keep_alive="1m"
)

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
    response = requests.get(
        url,
        timeout=30
    )

    response.raise_for_status()

    if not response.content.startswith(b"%PDF-"):
        raise InvalidPDFError(
            f"Invalid PDF file: {url}"
        )

    with open(save_path, "wb") as f:
        f.write(response.content)

    return save_path


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

def process_new_notices(limit=None):

    query = {
        "status": "new"
    }

    cursor = collection.find(query)

    if limit is not None:
        cursor = cursor.limit(limit)

    notices = list(cursor)
    total = len(notices)

    if total == 0:
        print("No new notices found.")
        return

    print("\n" + "=" * 60)
    print(f"UniAI Module 2 | Processing {total} notices")
    print("=" * 60)

    success_count = 0
    review_count = 0
    failed_count = 0
    invalid_count = 0

    for index, notice in enumerate(notices, start=1):

        notice_id = notice.get("notice_id")
        pdf_url = notice.get("url")
        title = notice.get("title") or "Untitled Notice"

        print(f"\n[{index}/{total}] {title[:75]}")

        if not notice_id or not pdf_url:
            failed_count += 1
            print("  -> Missing notice ID or URL")
            continue

        pdf_path = None

        try:
            # -----------------------------------------
            # Step 1: Temporary PDF
            # -----------------------------------------

            with tempfile.NamedTemporaryFile(
                suffix=".pdf",
                delete=False
            ) as temp_file:
                pdf_path = temp_file.name

            download_pdf(pdf_url, pdf_path)

            print("  -> PDF downloaded")

            # -----------------------------------------
            # Step 2: Extraction (Direct text / OCR)
            # -----------------------------------------

            raw_text = extract_pdf_text(pdf_path)

            if not isinstance(raw_text, str) or not raw_text.strip():
                raise ValueError("Extraction returned empty text")

            print(
                f"  -> Text extracted: "
                f"{len(raw_text)} characters"
            )

            # -----------------------------------------
            # Step 3: Choose Processing Strategy
            # -----------------------------------------

            is_long = len(raw_text) > SHORT_TEXT_LIMIT

            if is_long:
                structured_data, chunk_results = (
                    process_long_notice(raw_text)
                )
            else:
                structured_data = extract_structured_data(raw_text)
                chunk_results = None

            # -----------------------------------------
            # Step 4: MongoDB Update
            # -----------------------------------------

            update_fields = {
                "raw_text": raw_text,
                "structured_data": structured_data,
                "processed_at": datetime.now(timezone.utc),
                "extraction_model": MODEL_NAME,
                "requires_chunking": is_long
            }

            if is_long:
                update_fields.update({
                    "status": "review_required",
                    "quality_review_required": True,
                    "chunk_extractions": chunk_results,
                    "pinecone_indexed": False
                })

            else:
                update_fields.update({
                    "status": "processed",
                    "quality_review_required": False
                })

            update_result = collection.update_one(
                {
                    "_id": notice["_id"],
                    "status": "new"
                },
                {
                    "$set": update_fields,
                    "$unset": {
                        "processing_error": "",
                        "invalid_pdf_url": ""
                    }
                }
            )

            if update_result.matched_count != 1:
                raise RuntimeError(
                    "Notice changed before update"
                )

            if is_long:
                review_count += 1
                print(
                    "  -> SUCCESS: Long notice saved "
                    "for review"
                )
            else:
                success_count += 1
                print(
                    "  -> SUCCESS: Status = processed"
                )

        except InvalidPDFError as error:
            invalid_count += 1

            collection.update_one(
                {"_id": notice["_id"]},
                {
                    "$set": {
                        "status": "invalid",
                        "processing_error": str(error),
                        "invalid_pdf_url": pdf_url
                    }
                }
            )

            print(f"  -> INVALID PDF: {error}")

        except Exception as error:
            failed_count += 1

            print(f"  -> FAILED: {error}")

            collection.update_one(
                {
                    "_id": notice["_id"],
                    "status": "new"
                },
                {
                    "$set": {
                        "processing_error": str(error),
                        "last_failed_at": datetime.now(
                            timezone.utc
                        )
                    }
                }
            )

        finally:
            # -----------------------------------------
            # Step 5: Delete Temporary PDF
            # -----------------------------------------

            if pdf_path and os.path.exists(pdf_path):
                os.remove(pdf_path)

    # =================================================
    # 9. SUMMARY
    # =================================================

    print("\n" + "=" * 60)
    print("UniAI Module 2 | Batch Summary")
    print("=" * 60)

    print(f"Total checked   : {total}")
    print(f"Processed       : {success_count}")
    print(f"Review required : {review_count}")
    print(f"Failed          : {failed_count}")
    print(f"Invalid PDFs    : {invalid_count}")

    print("=" * 60)


# =====================================================
# 10. ENTRY POINT
# =====================================================

if __name__ == "__main__":
    try:
        process_new_notices(limit=2)
    finally:
        client.close()
