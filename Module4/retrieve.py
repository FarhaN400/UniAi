import os
import re
import json
from datetime import datetime, timezone, timedelta

from pymongo import MongoClient
from dotenv import load_dotenv
from pinecone import Pinecone


load_dotenv()

# --------------------------------------------------
# MongoDB
# --------------------------------------------------

MONGO_URI = os.getenv("MONGO_URI")

client = MongoClient(MONGO_URI)

notices_collection = client[
    "university_assistant"
]["university_documents"]


# --------------------------------------------------
# Pinecone
# --------------------------------------------------

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")

pc = Pinecone(api_key=PINECONE_API_KEY)

index = pc.Index("uniai")


# --------------------------------------------------
# Helper Functions
# --------------------------------------------------

def extract_year_from_question(question):
    """
    Extract a specific year such as 2025 or 2026
    from the student's question.
    """

    match = re.search(r'\b(20\d{2})\b', question)

    return int(match.group(1)) if match else None


def is_time_based_query(question):
    """
    Detect questions asking about recent/latest notices.
    """

    question = question.lower()

    time_keywords = [
        "latest",
        "recent",
        "today",
        "today's",
        "new notification",
        "new notice",
        "new notifications",
        "new notices",
        "yesterday"
    ]

    return any(keyword in question for keyword in time_keywords)


# --------------------------------------------------
# Time-based MongoDB Retrieval
# --------------------------------------------------

def retrieve_time_based(question, top_k=3):
    """
    Retrieve latest/today/yesterday notices directly
    from MongoDB, preferring the official notice issue date.
    """

    question_lower = question.lower()
    now = datetime.now(timezone.utc)

    query = {"status": "processed"}
    records = list(notices_collection.find(query))

    def normalize_datetime(value):
        if value is None:
            return datetime.min.replace(tzinfo=timezone.utc)
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        return datetime.min.replace(tzinfo=timezone.utc)

    def parse_issue_date(record):
        issue_date = record.get("structured_data", {}).get("issue_date")
        if not issue_date:
            return normalize_datetime(record.get("detected_at"))

        for fmt in ("%d-%m-%Y", "%d-%m-%Y %H:%M"):
            try:
                dt = datetime.strptime(issue_date, fmt)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue

        return normalize_datetime(record.get("detected_at"))

    # -----------------------------
    # TODAY
    # -----------------------------
    if "today" in question_lower or "today's" in question_lower:
        start_of_today = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        end_of_today = start_of_today + timedelta(days=1)
        records = [
            r for r in records
            if start_of_today <= parse_issue_date(r) < end_of_today
        ]

    # -----------------------------
    # YESTERDAY
    # -----------------------------
    elif "yesterday" in question_lower:
        start_of_today = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        start_of_yesterday = start_of_today - timedelta(days=1)
        records = [
            r for r in records
            if start_of_yesterday <= parse_issue_date(r) < start_of_today
        ]

    # -----------------------------
    # LATEST / RECENT
    # -----------------------------
    records = sorted(records, key=parse_issue_date, reverse=True)
    return records[:top_k]


def retrieve_topic_notices(topic, top_k=3):
    """Return notices mentioning a specific topic, newest official issue date first."""
    pattern = re.compile(re.escape(topic), re.IGNORECASE)
    title_query = {
        "status": "processed",
        "structured_data.title": pattern,
    }
    records = list(notices_collection.find(title_query))

    if not records:
        scraped_title_query = {
            "status": "processed",
            "title": pattern,
        }
        records = list(notices_collection.find(scraped_title_query))

    if not records:
        body_query = {
            "status": "processed",
            "$or": [
                {"raw_text": pattern},
                {"structured_data.key_points": pattern},
            ],
        }
        records = list(notices_collection.find(body_query))

    def issue_date(record):
        value = record.get("structured_data", {}).get("issue_date")
        if value:
            for fmt in ("%d-%m-%Y", "%d-%m-%Y %H:%M"):
                try:
                    return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
                except ValueError:
                    continue

        detected_at = record.get("detected_at")
        if isinstance(detected_at, datetime):
            return detected_at.replace(tzinfo=timezone.utc) if detected_at.tzinfo is None else detected_at
        return datetime.min.replace(tzinfo=timezone.utc)

    records.sort(key=issue_date, reverse=True)
    return records[:top_k]


# --------------------------------------------------
# Semantic Retrieval
# --------------------------------------------------

def retrieve_semantic(question, top_k=3):
    """
    Search Pinecone semantically.

    If the student mentions a year, apply the
    corresponding Pinecone metadata filter.

    Pinecone returns notice IDs, which are then
    used to retrieve complete records from MongoDB.
    """

    year = extract_year_from_question(question)

    query_params = {
        "inputs": {
            "text": question
        },
        "top_k": top_k
    }

    # Optional year filtering
    if year:

        query_params["filter"] = {
            "year": {
                "$eq": year
            }
        }

    try:

        results = index.search_records(
            namespace="notices",
            query=query_params
        )

    except Exception as e:

        print(f"Pinecone search failed: {e}")

        return []


    # --------------------------------------------------
    # Extract IDs from Pinecone results
    # --------------------------------------------------

    if isinstance(results, dict):

        hits = (
            results
            .get("result", {})
            .get("hits", [])
        )

    else:

        result_object = getattr(
            results,
            "result",
            None
        )

        hits = getattr(
            result_object,
            "hits",
            []
        )


    notice_ids = []

    for hit in hits:

        if isinstance(hit, dict):

            notice_id = (
                hit.get("id")
                or hit.get("_id")
            )

        else:

            notice_id = (
                getattr(hit, "id", None)
                or getattr(hit, "_id", None)
            )

        if notice_id:

            notice_ids.append(notice_id)


    # --------------------------------------------------
    # Retrieve full documents from MongoDB
    # --------------------------------------------------

    full_records = []

    for notice_id in notice_ids:

        try:

            record = notices_collection.find_one({
                "notice_id": notice_id
            })

            if record:

                full_records.append(record)

        except Exception as e:

            print(
                f"MongoDB fetch failed "
                f"for {notice_id}: {e}"
            )

    return full_records


# --------------------------------------------------
# Main Retrieval Router
# --------------------------------------------------

def retrieve_context(question, top_k=3):
    """
    Decide which retrieval strategy should be used.

    Time-based question:
        MongoDB date-based retrieval

    Normal information question:
        Pinecone semantic retrieval
    """

    if is_time_based_query(question):

        return retrieve_time_based(
            question,
            top_k
        )

    return retrieve_semantic(
        question,
        top_k
    )


# --------------------------------------------------
# Context Builder
# --------------------------------------------------

def build_context_string(records):
    """
    Build LLM context using complete structured
    notice information.
    """

    if not records:

        return "No relevant notices were found."


    context_blocks = []


    for r in records:

        structured_data = r.get(
            "structured_data",
            {}
        )

        detected_at = r.get(
            "detected_at"
        )

        context_blocks.append(
            f"Notice Data:\n"
            f"{json.dumps(structured_data, indent=2, default=str)}\n"
            f"Detected At: {detected_at}\n"
            f"Source URL: {r.get('url')}"
        )


    return "\n\n---\n\n".join(
        context_blocks
    )