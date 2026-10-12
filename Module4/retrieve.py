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

def _get_hit_value(hit, key, default=None):
    return hit.get(key, default) if isinstance(hit, dict) else getattr(hit, key, default)


def _get_hits(results):
    result = _get_hit_value(results, "result", {})
    return _get_hit_value(result, "hits", []) or []


def _document_year_matches(record, year):
    """Check the whole notice (not just issue_date, which may differ from admission year)."""
    if year is None:
        return True
    data = record.get("structured_data") or {}
    searchable = " ".join(str(x) for x in (
        record.get("title", ""), data.get("title", ""),
        data.get("summary", ""), data.get("academic_year", ""),
        data.get("key_points", ""), record.get("url", "")))
    return bool(re.search(rf"(?<!\d){year}(?!\d)", searchable))


def _lexical_score(question, record):
    """Small lexical reranker to supplement the Pinecone similarity score."""
    data = record.get("structured_data") or {}
    title = str(data.get("title") or record.get("title") or "").lower()
    text = " ".join(str(v) for v in (
        title, data.get("summary", ""), data.get("key_points", ""),
        data.get("notice_type", ""), data.get("action_required", ""))).lower()
    tokens = set(re.findall(r"[a-z]{3,}", question.lower())) - {
        "what", "when", "which", "where", "with", "from", "does", "that",
        "this", "students", "student", "makaut", "notice", "notices",
        "required", "mentioned", "please", "about", "for", "the", "and"}
    title_words = set(re.findall(r"[a-z]{3,}", title))
    body_words = set(re.findall(r"[a-z]{3,}", text))
    score = 2 * len(tokens & title_words) + len(tokens & body_words)
    # Document verification is a distinct intent, not interchangeable with registration closure.
    if re.search(r"document|verification|bring", question, re.I):
        if re.search(r"document|verification", text):
            score += 5
        if "registration portal" in title and "verification" not in title:
            score -= 3
    return score


def retrieve_semantic(question, top_k=5):
    """Retrieve Pinecone candidates and resolve them through MongoDB.

    First try an indexed numeric year filter. If this yields no usable matches,
    search without the filter and verify year against MongoDB document content.
    This avoids silently dropping notices with absent/wrong-type year metadata.
    """
    year = extract_year_from_question(question)
    debug = os.getenv("UNIAI_DEBUG", "0") == "1"
    candidate_k = max(top_k, 15)
    filtered_query = {"inputs": {"text": question}, "top_k": candidate_k}
    if year is not None:
        filtered_query["filter"] = {"year": {"$eq": year}}

    def search(params):
        try:
            response = index.search_records(namespace="notices", query=params)
            return _get_hits(response)
        except Exception as exc:
            print(f"[UniAI] Pinecone search error: {exc}")
            return []

    hits = search(filtered_query)
    if year is not None and not hits:
        if debug:
            print(f"[UniAI] No indexed hits for numeric year={year}; retrying without metadata filter")
        hits = search({"inputs": {"text": question}, "top_k": max(candidate_k, 40)})

    def records_from_hits(hits_list):
        rows = []
        seen = set()
        for position, hit in enumerate(hits_list):
            notice_id = _get_hit_value(hit, "_id") or _get_hit_value(hit, "id")
            if not notice_id or notice_id in seen:
                continue
            seen.add(notice_id)
            record = notices_collection.find_one({"notice_id": notice_id})
            if record is None:
                if debug:
                    print(f"[UniAI] Pinecone ID absent from MongoDB: {notice_id}")
                continue
            raw_score = _get_hit_value(hit, "_score", _get_hit_value(hit, "score", 0))
            try:
                semantic = float(raw_score or 0)
            except (TypeError, ValueError):
                semantic = 0
            record_score = _lexical_score(question, record)
            rows.append((record, record_score, semantic, position))
            if debug:
                print(f"[UniAI] hit={position + 1} score={semantic:.4f} "
                      f"lexical={record_score} title={record.get('title')} id={notice_id}")
        return rows

    rows = records_from_hits(hits)
    if year is not None:
        matches = [r for r in rows if _document_year_matches(r[0], year)]
        if not matches:
            # Fallback if indexed metadata is inaccurate or semantic candidate pool is too narrow.
            hits = search({"inputs": {"text": question}, "top_k": max(candidate_k, 40)})
            matches = [r for r in records_from_hits(hits) if _document_year_matches(r[0], year)]
        rows = matches
        if not rows:
            # Last resort for legacy notices missing from the vector index.
            # Limited, year-targeted MongoDB scan (not a general answer shortcut).
            year_pattern = re.compile(str(year), re.IGNORECASE)
            legacy = notices_collection.find({"status": "processed", "$or": [
                {"title": year_pattern}, {"structured_data.title": year_pattern},
                {"structured_data.summary": year_pattern}]})
            for record in legacy:
                if _document_year_matches(record, year):
                    rows.append((record, _lexical_score(question, record), 0.0, 999))
            if debug:
                print(f"[UniAI] legacy MongoDB year fallback: {len(rows)} candidates")

    # Prefer full-question relevance; semantic score breaks lexical ties.
    rows.sort(key=lambda row: (row[1], row[2]), reverse=True)
    return [row[0] for row in rows[:top_k]]


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