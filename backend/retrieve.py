import os
import re
import json
import math
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
# Helper Functions: Year and Date Parsing
# --------------------------------------------------

def extract_year_from_question(question):
    """
    Extract a specific 4-digit year or academic session start year
    from the student's question (e.g., '2026', '2026-27').
    """
    if not question:
        return None

    # Academic session pattern (e.g. 2026-27, 2026-2027)
    session_match = re.search(r'\b(20\d{2})[-/](?:\d{2}|\d{4})\b', question)
    if session_match:
        return int(session_match.group(1))

    # Single 4-digit year
    match = re.search(r'\b(20\d{2})\b', question)
    return int(match.group(1)) if match else None


def normalize_datetime(value):
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return datetime.min.replace(tzinfo=timezone.utc)


def parse_issue_date(record):
    """Parse the official issue date from structured data or detected_at."""
    sd = record.get("structured_data") or {}
    issue_date = sd.get("issue_date")
    if issue_date:
        for fmt in ("%d-%m-%Y", "%d-%m-%Y %H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(str(issue_date).strip(), fmt)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue

    return normalize_datetime(record.get("detected_at"))


def is_pure_time_query(question):
    """
    Detect questions strictly asking for newest/recent notices without a specific topic.
    e.g. 'latest notices', 'give me today's notices', 'recent notifications'.
    """
    text = (question or "").lower()
    time_terms = [
        "latest", "recent", "today", "today's", "yesterday",
        "new notice", "new notices", "new notification", "new notifications"
    ]
    has_time = any(t in text for t in time_terms)
    if not has_time:
        return False

    # Check if there is a specific informational topic
    topic_indicators = [
        "wbjee", "wbjeeb", "jelet", "jeca", "hostel", "scholarship", "exam",
        "examination", "fee", "fees", "refund", "cancellation", "admission",
        "registration", "placement", "syllabus", "routine", "discipline",
        "ragging", "holiday", "puja", "documents", "eligibility"
    ]
    has_topic = any(t in text for t in topic_indicators)
    return not has_topic


# --------------------------------------------------
# Raw Text Excerpt Extraction
# --------------------------------------------------

def extract_relevant_snippets(raw_text, question, max_snippets=2, max_chars=450):
    """
    Extract the most informative paragraphs/sentences from raw_text
    matching key terms in the student's question.
    Preserves exact fine-grained details like URLs, bank accounts, dates, and steps.
    """
    if not raw_text or not question:
        return []

    tokens = set(re.findall(r"[a-z0-9]{3,}", question.lower())) - {
        "what", "when", "which", "where", "with", "from", "does", "that",
        "this", "these", "those", "students", "student", "makaut", "notice",
        "notices", "required", "mentioned", "please", "about", "for", "the",
        "and", "give", "tell", "show", "details", "information"
    }

    if not tokens:
        return []

    # Process sliding windows of lines to handle both double-newlines and single-line OCR outputs
    lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
    chunks = []
    chunk_size = 4
    step = 2
    for i in range(0, max(1, len(lines)), step):
        window = " ".join(lines[i:i + chunk_size])
        if len(window) > 30:
            chunks.append(window)

    if not chunks and raw_text.strip():
        chunks = [raw_text.strip()]

    scored = []
    for c in chunks:
        c_lower = c.lower()
        score = sum(3 for t in tokens if t in c_lower)

        # Bonus for containing links, steps, or numerical/date info
        if "http" in c_lower or "portal" in c_lower or "login" in c_lower:
            score += 4
        if re.search(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b", c):
            score += 2
        if re.search(r"\b(?:rs\.?|inr)\s*\d+", c_lower):
            score += 2

        if score > 0:
            scored.append((score, c))

    scored.sort(key=lambda x: x[0], reverse=True)

    selected = []
    seen = set()
    for _, c in scored:
        clean = " ".join(c.split())
        fingerprint = clean[:60]
        if fingerprint in seen:
            continue
        seen.add(fingerprint)

        if len(clean) > max_chars:
            clean = clean[:max_chars].rsplit(" ", 1)[0] + "…"

        selected.append(clean)
        if len(selected) >= max_snippets:
            break

    return selected


# --------------------------------------------------
# Document Year Matching
# --------------------------------------------------

def _document_year_matches(record, year):
    """
    Check if a document refers to the requested year anywhere in its metadata,
    structured data, or full raw text.
    """
    if year is None:
        return True

    data = record.get("structured_data") or {}
    searchable = " ".join(str(x) for x in (
        record.get("title", ""),
        data.get("title", ""),
        data.get("summary", ""),
        data.get("academic_year", ""),
        data.get("key_points", ""),
        record.get("url", ""),
        record.get("raw_text", "")[:3000]
    ))

    # Look for exact 4-digit year boundary (e.g. '2026' or '2026-27')
    return bool(re.search(rf"(?<!\d){year}(?!\d)", searchable))


# --------------------------------------------------
# Lexical BM25-Style Scoring
# --------------------------------------------------

def _lexical_score(question, record):
    """
    Weighted term frequency matching across title, summary, key points, and raw text.
    """
    data = record.get("structured_data") or {}
    title = str(data.get("title") or record.get("title") or "").lower()
    summary = str(data.get("summary") or "").lower()
    key_points = " ".join(str(p) for p in (data.get("key_points") or [])).lower()
    raw_preview = str(record.get("raw_text") or "")[:2000].lower()

    tokens = set(re.findall(r"[a-z0-9]{3,}", question.lower())) - {
        "what", "when", "which", "where", "with", "from", "does", "that",
        "this", "these", "those", "students", "student", "makaut", "notice",
        "notices", "required", "mentioned", "please", "about", "for", "the",
        "and", "give", "tell", "show"
    }

    if not tokens:
        return 0.0

    score = 0.0
    for token in tokens:
        if token in title:
            score += 4.0
        if token in summary or token in key_points:
            score += 2.0
        if token in raw_preview:
            score += 1.0

    # Phrase match bonus for multi-word exact matches
    clean_q = " ".join(question.lower().split())
    for phrase_len in (3, 2):
        words = clean_q.split()
        for i in range(len(words) - phrase_len + 1):
            phrase = " ".join(words[i:i + phrase_len])
            if len(phrase) >= 6 and phrase in title:
                score += 5.0
            elif len(phrase) >= 6 and phrase in summary:
                score += 2.5

    return score


# --------------------------------------------------
# Time-based MongoDB Retrieval
# --------------------------------------------------

def retrieve_time_based(question, top_k=3):
    """
    Retrieve newest/today/yesterday notices chronologically from MongoDB,
    ordered by official notice issue date.
    """
    question_lower = (question or "").lower()
    now = datetime.now(timezone.utc)

    query = {"status": "processed"}
    records = list(notices_collection.find(query).sort([
        ("status", 1),
        ("detected_at", -1)
    ]))

    # TODAY
    if "today" in question_lower or "today's" in question_lower:
        start_of_today = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        end_of_today = start_of_today + timedelta(days=1)
        records = [
            r for r in records
            if start_of_today <= parse_issue_date(r) < end_of_today
        ]

    # YESTERDAY
    elif "yesterday" in question_lower:
        start_of_today = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        start_of_yesterday = start_of_today - timedelta(days=1)
        records = [
            r for r in records
            if start_of_yesterday <= parse_issue_date(r) < start_of_today
        ]

    # LATEST / RECENT
    records = sorted(records, key=parse_issue_date, reverse=True)
    return records[:top_k]


def retrieve_topic_notices(topic, top_k=3):
    """
    Retrieve notices mentioning a specific topic (e.g. 'wbjee', 'hostel'),
    sorted newest official issue date first.
    """
    pattern = re.compile(re.escape(topic), re.IGNORECASE)

    # 1. Search title
    records = list(notices_collection.find({
        "status": "processed",
        "$or": [
            {"structured_data.title": pattern},
            {"title": pattern}
        ]
    }))

    # 2. Search body / key points if sparse
    if len(records) < top_k:
        existing_ids = {r["_id"] for r in records}
        body_records = list(notices_collection.find({
            "status": "processed",
            "_id": {"$nin": list(existing_ids)},
            "$or": [
                {"structured_data.summary": pattern},
                {"structured_data.key_points": pattern},
                {"raw_text": pattern}
            ]
        }))
        records.extend(body_records)

    records.sort(key=parse_issue_date, reverse=True)
    return records[:top_k]


# --------------------------------------------------
# Semantic & Hybrid Retrieval with RRF
# --------------------------------------------------

def _get_hit_value(hit, key, default=None):
    return hit.get(key, default) if isinstance(hit, dict) else getattr(hit, key, default)


def _get_hits(results):
    result = _get_hit_value(results, "result", {})
    return _get_hit_value(result, "hits", []) or []


def retrieve_semantic(question, top_k=5):
    """
    Advanced Hybrid Retrieval:
    1. Pinecone dense vector search (high recall candidate pool).
    2. BM25-style lexical scoring across structured fields and raw text.
    3. Reciprocal Rank Fusion (RRF) combining dense & sparse ranks.
    4. Year-awareness and soft recency decay for non-historical queries.
    """
    year = extract_year_from_question(question)
    debug = os.getenv("UNIAI_DEBUG", "0") == "1"
    candidate_k = max(top_k * 4, 25)

    def search_pinecone(filter_dict=None):
        try:
            query_params = {
                "inputs": {"text": question},
                "top_k": candidate_k
            }
            if filter_dict:
                query_params["filter"] = filter_dict
            response = index.search_records(namespace="notices", query=query_params)
            return _get_hits(response)
        except Exception as exc:
            print(f"[UniAI] Pinecone search error: {exc}")
            return []

    # Try filtered search if year was explicitly specified
    hits = []
    if year is not None:
        hits = search_pinecone(filter_dict={"year": {"$eq": year}})

    # If no hits or no year specified, query dense index broadly
    if not hits:
        hits = search_pinecone()

    # Collect unique MongoDB records from hits
    records_by_id = {}
    dense_ranks = {}

    for pos, hit in enumerate(hits):
        notice_id = _get_hit_value(hit, "_id") or _get_hit_value(hit, "id")
        if not notice_id or notice_id in records_by_id:
            continue

        record = notices_collection.find_one({"notice_id": notice_id, "status": "processed"})
        if record:
            records_by_id[notice_id] = record
            dense_ranks[notice_id] = pos + 1

    # Also pull keyword candidate notices directly from MongoDB if query has specific keywords
    tokens = set(re.findall(r"[a-z0-9]{3,}", question.lower())) - {
        "what", "when", "which", "where", "with", "from", "does", "that",
        "this", "these", "those", "students", "student", "makaut", "notice",
        "notices", "required", "mentioned", "please", "about", "for", "the", "and"
    }
    if tokens:
        keyword_regex = "|".join(re.escape(t) for t in list(tokens)[:4])
        pattern = re.compile(keyword_regex, re.IGNORECASE)
        mongo_candidates = list(notices_collection.find({
            "status": "processed",
            "$or": [
                {"title": pattern},
                {"structured_data.title": pattern},
                {"structured_data.summary": pattern}
            ]
        }).limit(20))

        for mc in mongo_candidates:
            nid = mc.get("notice_id")
            if nid and nid not in records_by_id:
                records_by_id[nid] = mc

    if not records_by_id:
        return []

    # Calculate Sparse / Lexical Score for each candidate
    candidate_records = list(records_by_id.values())
    lexical_scored = []
    for r in candidate_records:
        l_score = _lexical_score(question, r)
        lexical_scored.append((r, l_score))

    # Rank candidates by lexical score
    lexical_scored.sort(key=lambda x: x[1], reverse=True)
    sparse_ranks = {}
    for pos, (r, _) in enumerate(lexical_scored):
        nid = r.get("notice_id")
        sparse_ranks[nid] = pos + 1

    # Reciprocal Rank Fusion (RRF) with Recency Decay
    now = datetime.now(timezone.utc)
    fused_candidates = []

    for r in candidate_records:
        nid = r.get("notice_id")
        r_dense = dense_ranks.get(nid, 999)
        r_sparse = sparse_ranks.get(nid, 999)

        # Standard RRF formula (k=60)
        rrf_score = (1.0 / (60.0 + r_dense)) + (1.0 / (60.0 + r_sparse))

        # Year validation
        if year is not None:
            if not _document_year_matches(r, year):
                # Strongly demote documents conflicting with requested year
                rrf_score *= 0.1
            else:
                rrf_score *= 1.5

        # Soft recency decay when no specific historical year is asked
        if year is None:
            doc_date = parse_issue_date(r)
            days_ago = max(0, (now - doc_date).days)
            # Gentle exponential decay: ~1.0 for recent, ~0.8 for 1 year, ~0.65 for 2 years
            recency_mult = math.exp(-0.0006 * days_ago)
            rrf_score *= recency_mult

        fused_candidates.append((r, rrf_score))

    fused_candidates.sort(key=lambda x: x[1], reverse=True)

    if debug:
        print(f"[UniAI Hybrid] Retrieved {len(fused_candidates)} candidates for: '{question}'")
        for i, (rec, sc) in enumerate(fused_candidates[:5], 1):
            print(f"  #{i} score={sc:.5f} date={parse_issue_date(rec).strftime('%d-%m-%Y')} title={rec.get('title')}")

    return [c[0] for c in fused_candidates[:top_k]]


# --------------------------------------------------
# Main Retrieval Router
# --------------------------------------------------

def retrieve_context(question, top_k=3):
    """
    Smart Retrieval Router:
    1. If strictly asking for newest/today/yesterday without topic -> Pure time retrieval.
    2. Otherwise -> Hybrid dense + sparse semantic retrieval with recency weighting.
    """
    if is_pure_time_query(question):
        return retrieve_time_based(question, top_k)

    return retrieve_semantic(question, top_k)


# --------------------------------------------------
# Enriched Context Builder
# --------------------------------------------------

def build_context_string(records, question=None):
    """
    Build rich, factual LLM context combining:
    1. Full structured notice dimensions (Dates, Fees, Actions, Key Points).
    2. Exact relevant snippets from raw_text matching the student query.
    3. Official URL citations.
    """
    if not records:
        return "No relevant notices were found."

    context_blocks = []

    for idx, r in enumerate(records, 1):
        sd = r.get("structured_data") or {}
        title = sd.get("title") or r.get("title") or "Untitled Notice"
        notice_type = sd.get("notice_type", "General")
        issue_date = sd.get("issue_date") or "Not specified"
        ref_no = sd.get("reference_no") or "Not specified"
        target_audience = sd.get("target_audience") or "All Students"
        summary = sd.get("summary") or "No summary available."
        action_required = sd.get("action_required") or "None"
        key_points = sd.get("key_points") or []
        dates = sd.get("important_dates") or {}
        fees = sd.get("fees") or {}
        url = r.get("url") or "Not available"

        block = [
            f"[NOTICE #{idx}]",
            f"Title: {title}",
            f"Type: {notice_type} | Issue Date: {issue_date} | Reference No: {ref_no}",
            f"Target Audience: {target_audience}",
            f"Summary: {summary}",
        ]

        # Important Dates
        if dates.get("start_date") or dates.get("last_date"):
            date_info = []
            if dates.get("start_date"):
                date_info.append(f"Start Date: {dates['start_date']}")
            if dates.get("last_date"):
                date_info.append(f"Last/Closing Date: {dates['last_date']}")
            block.append("Important Dates: " + " | ".join(date_info))

        # Fees
        if fees.get("amount") is not None:
            block.append(f"Fee: {fees.get('amount')} {fees.get('currency', '')}".strip())

        # Action Required
        if action_required and action_required != "None":
            block.append(f"Action Required: {action_required}")

        # Key Points
        if key_points:
            block.append("Key Points:\n" + "\n".join(f" - {kp}" for kp in key_points))

        # Dynamic Raw Text Snippets (Critical for capturing fine details omitted in summary)
        raw_text = r.get("raw_text") or ""
        if raw_text and question:
            snippets = extract_relevant_snippets(raw_text, question, max_snippets=2, max_chars=400)
            if snippets:
                block.append("Official Circular Excerpts:\n" + "\n".join(f" > \"{s}\"" for s in snippets))

        block.append(f"Official Source URL: {url}")
        context_blocks.append("\n".join(block))

    return "\n\n" + ("=" * 45) + "\n\n".join(context_blocks) + "\n" + ("=" * 45)