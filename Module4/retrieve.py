import os
import re
from pymongo import MongoClient
from dotenv import load_dotenv
from pinecone import Pinecone

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

# --- MongoDB ---
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
notices_collection = client["university_assistant"]["university_documents"]

# --- Pinecone ---
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
pc = Pinecone(api_key=PINECONE_API_KEY)
index = pc.Index("uniai")


def extract_year_from_question(question):
    """If the student mentions a specific year, return it; else None."""
    match = re.search(r'\b(20\d{2})\b', question)
    return int(match.group(1)) if match else None


def retrieve_context(question, top_k=3):
    """
    Search Pinecone (with optional year filter nested inside query),
    then fetch the full matching documents from MongoDB.
    """
    year = extract_year_from_question(question)

    query_params = {
        "inputs": {"text": question},
        "top_k": top_k
    }

    if year:
        query_params["filter"] = {"year": {"$eq": year}}

    try:
        results = index.search_records(
            namespace="notices",
            query=query_params
        )
    except Exception as e:
        print(f"Pinecone search failed: {e}")
        return []

    notice_ids = [hit["_id"] for hit in results["result"]["hits"]]

    full_records = []
    for notice_id in notice_ids:
        try:
            record = notices_collection.find_one({"notice_id": notice_id})
            if record:
                full_records.append(record)
        except Exception as e:
            print(f"MongoDB fetch failed for {notice_id}: {e}")

    return full_records


def build_context_string(records):
    """Format retrieved records into a clean context block for the LLM."""
    if not records:
        return "No relevant notices were found."

    context_blocks = []
    for r in records:
        sd = r.get("structured_data", {})
        context_blocks.append(
            f"Notice: {sd.get('title')}\n"
            f"Type: {sd.get('notice_type')}\n"
            f"Summary: {sd.get('summary')}\n"
            f"Key Points: {'; '.join(sd.get('key_points', []))}\n"
            f"Deadline: {sd.get('important_dates', {}).get('last_date')}\n"
            f"Source URL: {r.get('url')}"
        )
    return "\n\n---\n\n".join(context_blocks)