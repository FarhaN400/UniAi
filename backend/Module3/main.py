
import os
import re
from datetime import datetime, timezone

from pymongo import MongoClient
from dotenv import load_dotenv
from pinecone import Pinecone

load_dotenv()

# ---------------- MongoDB ----------------

MONGO_URI = os.getenv("MONGO_URI")

if not MONGO_URI:
    raise ValueError("MONGO_URI not found in .env")

client = MongoClient(MONGO_URI)
db = client["university_assistant"]
notices_collection = db["university_documents"]


# ---------------- Pinecone ----------------

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")

if not PINECONE_API_KEY:
    raise ValueError("PINECONE_API_KEY not found in .env")

pc = Pinecone(api_key=PINECONE_API_KEY)
index = pc.Index("uniai")

NAMESPACE = "notices"


# ---------------- Extract Year ----------------

def extract_year(notice):
    """
    Extract a 4-digit year from issue_date,
    falling back to the title.
    """

    sd = notice.get("structured_data") or {}

    issue_date = sd.get("issue_date") or ""

    match = re.search(r"(20\d{2})", issue_date)

    if match:
        return int(match.group(1))

    title = sd.get("title") or ""

    match = re.search(r"(20\d{2})", title)

    if match:
        return int(match.group(1))

    return None


# ---------------- Build Retrieval Text ----------------

def build_retrieval_text(notice):
    """
    Build meaningful retrieval text from
    structured university notice data.
    """

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

    # Include exact document names extracted from the official notice.
    required_documents = sd.get("required_documents") or []
    parts.extend(f"Required document: {doc}" for doc in required_documents if doc)

    # Include important dates
    dates = sd.get("important_dates") or {}

    if dates.get("start_date"):
        parts.append(
            f"Start date: {dates['start_date']}"
        )

    if dates.get("last_date"):
        parts.append(
            f"Last date: {dates['last_date']}"
        )

    # Include fees
    fees = sd.get("fees") or {}

    if fees.get("amount") is not None:
        amount = fees["amount"]
        currency = fees.get("currency") or ""

        fee_type = fees.get("type")
        label = f"{fee_type.capitalize()} fee" if fee_type else "Fee (unspecified type)"
        parts.append(
            f"{label}: {amount} {currency}".strip()
        )

    # Remove empty values
    text = "\n".join(
        str(part).strip()
        for part in parts
        if part is not None and str(part).strip()
    )

    return text


# ---------------- Index Single Notice ----------------

def index_one_notice(notice):

    sd = notice.get("structured_data") or {}

    text = build_retrieval_text(notice)

    if not text.strip():
        raise ValueError(
            "Cannot index notice with empty retrieval text"
        )

    notice_id = notice["notice_id"]
    year = extract_year(notice)

    record = {
        "id": notice_id,
        "text": text,
        "title": sd.get("title") or "",
        "notice_type": sd.get("notice_type") or "",
        "url": notice.get("url") or "",
    }

    if year is not None:
        record["year"] = year

    # Pinecone integrated embedding + upsert
    index.upsert_records(
        namespace=NAMESPACE,
        records=[record]
    )

    # Mark indexed only after successful Pinecone call
    result = notices_collection.update_one(
        {"_id": notice["_id"], "status": "processed",
         "pdf_sha256": notice.get("pdf_sha256"),
         "quality_review_required": {"$ne": True}},
        {
            "$set": {
                "pinecone_indexed": True,
                "pinecone_indexed_at": datetime.now(
                    timezone.utc
                )
            }
        }
    )

    if result.matched_count != 1:
        raise RuntimeError(
            "The notice changed during indexing; refusing to mark a stale "
            "Pinecone upsert as current. A newer extraction will be reindexed."
        )

    print(
        f"  -> Indexed: {sd.get('title')} "
        f"(year: {year})"
    )


# ---------------- Index Processed Notices ----------------

def index_all_processed_notices(limit=None, reindex=False):

    query = {
        "status": "processed",
        "quality_review_required": {"$ne": True},
        "structured_data": {"$type": "object"}
    }

    # Skip already indexed notices unless reindex=True
    if not reindex:
        query["$or"] = [
            {"pinecone_indexed": {"$exists": False}},
            {"pinecone_indexed": False}
        ]

    cursor = notices_collection.find(query).sort(
        [("processed_at", 1), ("detected_at", 1)]
    )

    if limit is not None:
        cursor = cursor.limit(limit)

    notices = list(cursor)

    print("\n" + "=" * 55)
    print("UniAI Module 3 | Pinecone Indexing")
    print("=" * 55)

    print(
        f"Found {len(notices)} eligible notices "
        f"to index.\n"
    )

    success_count = 0
    failed_count = 0

    for i, notice in enumerate(notices, start=1):

        print(
            f"[{i}/{len(notices)}] "
            f"{notice.get('title', 'Untitled Notice')}"
        )

        try:
            index_one_notice(notice)
            success_count += 1

        except Exception as error:
            failed_count += 1

            print(f"  -> FAILED: {error}")

    print("\n" + "=" * 55)
    print("UniAI Module 3 | Indexing Summary")
    print("=" * 55)

    print(f"Total selected : {len(notices)}")
    print(f"Indexed        : {success_count}")
    print(f"Failed         : {failed_count}")

    print("=" * 55)

    return success_count, failed_count


# ---------------- Main ----------------

if __name__ == "__main__":
    try:
        # First test with 3 notices
        index_all_processed_notices()

        # After successful testing, use:
        # index_all_processed_notices()

    finally:
        client.close()
