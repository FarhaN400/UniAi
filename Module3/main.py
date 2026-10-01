import os
import re
from datetime import datetime, timezone
from pymongo import MongoClient
from dotenv import load_dotenv
from pinecone import Pinecone

load_dotenv()

# --- MongoDB ---
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client["university_assistant"]
notices_collection = db["university_documents"]

# --- Pinecone ---
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
pc = Pinecone(api_key=PINECONE_API_KEY)
index = pc.Index("uniai")


def extract_year(notice):
    """Pull a 4-digit year from issue_date, falling back to the title if needed."""
    issue_date = notice["structured_data"].get("issue_date", "") or ""
    match = re.search(r'(20\d{2})', issue_date)
    if match:
        return int(match.group(1))

    title = notice["structured_data"].get("title", "") or ""
    match = re.search(r'(20\d{2})', title)
    if match:
        return int(match.group(1))

    return None


def build_retrieval_text(notice):
    sd = notice["structured_data"]
    parts = [
        sd.get("title", ""),
        sd.get("notice_type", ""),
        sd.get("summary", ""),
    ]
    key_points = sd.get("key_points", [])
    if key_points:
        parts.append(" ".join(key_points))
    deadline = sd.get("important_dates", {}).get("last_date")
    if deadline:
        parts.append(f"Deadline: {deadline}")
    return " ".join(p for p in parts if p)


def index_one_notice(notice):
    sd = notice.get("structured_data") or {}
    text = build_retrieval_text(notice)
    year = extract_year(notice)

    record = {
        "id": notice["notice_id"],
        "text": text,
        "title": sd.get("title"),
        "notice_type": sd.get("notice_type"),
        "url": notice["url"],
    }

    if year is not None:
        record["year"] = year

    index.upsert_records(
        namespace="notices",
        records=[record]
    )

    notices_collection.update_one(
        {"notice_id": notice["notice_id"]},
        {
            "$set": {
                "pinecone_indexed": True,
                "pinecone_indexed_at": datetime.now(timezone.utc)
            }
        }
    )

    print(f"Indexed: {sd.get('title')} (year: {year})")


def index_all_processed_notices(limit=None, reindex=False):
    query = {"status": "processed"}
    if not reindex:
        query["$or"] = [
            {"pinecone_indexed": {"$exists": False}},
            {"pinecone_indexed": False}
        ]

    cursor = notices_collection.find(query)
    if limit is not None:
        cursor = cursor.limit(limit)

    notices = list(cursor)
    print(f"Found {len(notices)} processed notices to index.\n")

    for notice in notices:
        index_one_notice(notice)

    print(f"\nDone. Indexed {len(notices)} notices into Pinecone.")


if __name__ == "__main__":
    index_all_processed_notices()