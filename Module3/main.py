import os
import re
from pymongo import MongoClient
from dotenv import load_dotenv
from pinecone import Pinecone

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

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
    text = build_retrieval_text(notice)
    year = extract_year(notice)

    record = {
        "id": notice["notice_id"],
        "text": text,
        "title": notice["structured_data"].get("title"),
        "notice_type": notice["structured_data"].get("notice_type"),
        "url": notice["url"],
    }

    if year is not None:
        record["year"] = year

    index.upsert_records(
        namespace="notices",
        records=[record]
    )
    print(f"Indexed: {notice['structured_data'].get('title')} (year: {year})")


def index_all_processed_notices(limit=None):
    query = {"status": "processed"}
    cursor = notices_collection.find(query)
    if limit:
        cursor = cursor.limit(limit)

    notices = list(cursor)
    print(f"Found {len(notices)} processed notices to index.\n")

    for notice in notices:
        index_one_notice(notice)

    print(f"\nDone. Indexed {len(notices)} notices into Pinecone.")


if __name__ == "__main__":
    index_all_processed_notices()