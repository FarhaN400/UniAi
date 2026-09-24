import os
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

    index.upsert_records(
        namespace="notices",
        records=[{
            "id": notice["notice_id"],
            "text": text,
            "title": notice["structured_data"].get("title"),
            "notice_type": notice["structured_data"].get("notice_type"),
            "url": notice["url"],
        }]
    )

    notices_collection.update_one(
        {"notice_id": notice["notice_id"]},
        {"$set": {
            "pinecone_indexed": True,
            "pinecone_indexed_at": datetime.now(timezone.utc)
        }}
    )
    print(f"Indexed: {notice['structured_data'].get('title')}")


def index_all_processed_notices(limit=None, reindex=False):
    if reindex:
        query = {"status": "processed"}
    else:
        query = {
            "status": "processed",
            "$or": [
                {"pinecone_indexed": {"$exists": False}},
                {"pinecone_indexed": False}
            ]
        }

    cursor = notices_collection.find(query)
    if limit:
        cursor = cursor.limit(limit)

    notices = list(cursor)
    print(f"Found {len(notices)} processed notices to index.\n")

    for notice in notices:
        index_one_notice(notice)

    print(f"\nDone. Indexed {len(notices)} notices into Pinecone.")


if __name__ == "__main__":
    # set limit for eg. , otherwise processed all notifications
    index_all_processed_notices(reindex=False)