"""UniAI Phase 3: retrieval and evidence-context preparation.

Public functions and signatures are kept compatible with Module4/main.py and
Module4/evidence.py. No schema migrations or Pinecone re-indexing are needed.
"""

import math
import os
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from pinecone import Pinecone
from pymongo import MongoClient

from notice_dates import official_issue_date
from academic_scope import (
    academic_sessions, requested_session, matches_session, matches_identity_year,
)

load_dotenv()

# Existing database / index names and Pinecone integrated embedding API.
MONGO_URI = os.getenv("MONGO_URI")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
client = MongoClient(MONGO_URI)
notices_collection = client["university_assistant"]["university_documents"]
pc = Pinecone(api_key=PINECONE_API_KEY)
index = pc.Index("uniai")

INDIA_TZ = ZoneInfo("Asia/Kolkata")
NAMESPACE = "notices"
DEBUG = lambda: os.getenv("UNIAI_DEBUG", "0").lower() in ("1", "true", "yes")

STOPWORDS = {
    "what", "when", "which", "where", "with", "from", "does", "that", "this",
    "these", "those", "student", "students", "makaut", "university", "notice",
    "notices", "notification", "notifications", "required", "mentioned",
    "please", "about", "for", "the", "and", "give", "tell", "show",
    "details", "information", "explain", "compare", "difference", "between",
    "first", "second", "third", "round", "latest", "recent", "dated", "issued",
}

# Only *explicitly mentioned* topic families get hard matching. Avoid treating
# incidental mentions of a WBJEEB website in a JECA document as a WBJEE notice.
TOPIC_ALIASES = {
    "wbjee": ("wbjeeb", "wbjee"),
    "jelet": ("jelet",),
    "jeca": ("jeca",),
    "jemat": ("jemat",),
    "pget": ("pget",),
    "cet": ("cet",),
    "hostel": ("hostel",),
    "scholarship": ("scholarship",),
    "ragging": ("ragging",),
}
ADMISSION_TOPICS = ("wbjee", "jelet", "jeca", "jemat", "pget", "cet")
ROUND_WORDS = {"first": 1, "1st": 1, "second": 2, "2nd": 2,
               "third": 3, "3rd": 3}
MONTH_NUMBERS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


def _tokens(text):
    return [t for t in re.findall(r"[a-z0-9]{3,}", str(text or "").lower())
            if t not in STOPWORDS]


def extract_year_from_question(question):
    """Return first explicitly requested year, including 2026-27 sessions."""
    text = str(question or "")
    match = re.search(r"\b(20\d{2})(?:[-/](?:20\d{2}|\d{2}))?\b", text)
    return int(match.group(1)) if match else None


def normalize_datetime(value):
    """Interpret MongoDB naive timestamps as UTC; compare in India local time."""
    if not isinstance(value, datetime):
        return datetime.min.replace(tzinfo=INDIA_TZ)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(INDIA_TZ)


def parse_issue_date(record):
    """Date for sorting only. Prefer official issue date; otherwise discovery.

    Never use this function as evidence for 'issued today', 'published
    yesterday', or an explicitly requested publication date. Those use
    official_issue_date(record) and reject missing/invalid values.
    """
    value = official_issue_date(record)
    if value is not None:
        return datetime(value.year, value.month, value.day, tzinfo=INDIA_TZ)
    return normalize_datetime(record.get("detected_at"))


def _explicit_issue_date(question):
    """Extract a notice's issue date, not an application/reporting deadline."""
    text = str(question or "").lower()
    marker = re.search(
        r"\b(?:notice|notification|circular|order)\b[^.!?]{0,100}?"
        r"\b(?:dated|issued\s+on|published\s+on)\s+", text
    )
    if not marker:
        return None
    tail = text[marker.end():marker.end() + 40]
    match = re.match(r"(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)\s*,?\s*(20\d{2})", tail)
    if match:
        day, month, year = match.groups()
        if month in MONTH_NUMBERS:
            try:
                return date(int(year), MONTH_NUMBERS[month], int(day))
            except ValueError:
                return None
    for fmt, pattern in (
        ("%d-%m-%Y", r"\d{1,2}-\d{1,2}-20\d{2}"),
        ("%d/%m/%Y", r"\d{1,2}/\d{1,2}/20\d{2}"),
        ("%Y-%m-%d", r"20\d{2}-\d{1,2}-\d{1,2}"),
    ):
        m = re.match(pattern, tail)
        if m:
            try:
                return datetime.strptime(m.group(0), fmt).date()
            except ValueError:
                return None
    return None


def _requested_rounds(question):
    text = str(question or "").lower()
    rounds = set()
    for word, number in ROUND_WORDS.items():
        if re.search(rf"\b{word}\s*[- ]?\s*(?:round|counselling|counseling)\b"
                     rf"|\bround\s*{word}\b", text):
            rounds.add(number)
    for match in re.finditer(r"\bround\s*(?:no\.?\s*)?([1-3])\b", text):
        rounds.add(int(match.group(1)))
    return rounds


def _record_rounds(record):
    data = record.get("structured_data") or {}
    primary = " ".join(str(value or "") for value in (
        record.get("title"), data.get("title"), data.get("admission_round"),
        data.get("round"), data.get("target_audience"),
    )).lower()
    detected = _requested_rounds(primary)
    if detected:
        return detected
    # Fall back to body only if primary metadata does not identify the round.
    secondary = " ".join(str(value or "") for value in (
        data.get("action_required"), data.get("key_points"),
        str(record.get("raw_text") or "")[:1500],
    )).lower()
    return _requested_rounds(secondary)


def _explicit_topics(question):
    text = str(question or "").lower()
    found = set()
    for topic, aliases in TOPIC_ALIASES.items():
        if any(re.search(rf"\b{re.escape(a)}\b", text) for a in aliases):
            found.add(topic)
    return found


def _primary_topic(record):
    """Resolve the notice's MAIN subject, avoiding incidental website links."""
    data = record.get("structured_data") or {}
    primary = " ".join(str(value or "") for value in (
        record.get("title"), data.get("title"), data.get("target_audience"),
    )).lower()
    for topic in ADMISSION_TOPICS:
        if any(re.search(rf"\b{re.escape(a)}\b", primary)
               for a in TOPIC_ALIASES[topic]):
            return topic
    for topic in TOPIC_ALIASES:
        if any(re.search(rf"\b{re.escape(a)}\b", primary)
               for a in TOPIC_ALIASES[topic]):
            return topic
    return None


def _topic_matches(record, requested_topics):
    if not requested_topics:
        return True
    main_topic = _primary_topic(record)
    if main_topic:
        return main_topic in requested_topics
    # A notice without a recognizable title can still be relevant via summary.
    data = record.get("structured_data") or {}
    fallback = " ".join(str(value or "") for value in (
        data.get("summary"), data.get("key_points"),
        data.get("action_required"),
    )).lower()
    return any(re.search(rf"\b{re.escape(alias)}\b", fallback)
               for topic in requested_topics for alias in TOPIC_ALIASES[topic])


def is_pure_time_query(question):
    """Time-only requests use MongoDB chronology, not Pinecone semantic ranking."""
    text = str(question or "").lower()
    has_time = bool(re.search(
        r"\b(?:latest|recent|today|yesterday|new\s+notices?|new\s+notifications?)\b",
        text,
    ))
    if not has_time:
        return False
    # A year or academic-session constraint means this is NOT global latest.
    if extract_year_from_question(question) is not None:
        return False
    if _explicit_topics(question):
        return False
    topic_indicators = (
        "exam", "examination", "fee", "refund", "admission", "registration",
        "placement", "syllabus", "routine", "discipline", "holiday",
        "vacant", "seat", "verification", "document", "eligibility", "counselling",
    )
    return not any(re.search(rf"\b{word}s?\b", text) for word in topic_indicators)


def extract_relevant_snippets(raw_text, question, max_snippets=2, max_chars=450):
    """Extract high-signal OCR snippets with bounded length and no text rewriting."""
    if not raw_text or not question or max_snippets <= 0:
        return []
    tokens = set(_tokens(question))
    if not tokens:
        return []
    lines = [line.strip() for line in str(raw_text).splitlines() if line.strip()]
    chunks = [" ".join(lines[i:i + 4]) for i in range(0, len(lines), 2)]
    chunks = [chunk for chunk in chunks if len(chunk) > 30]
    if not chunks:
        chunks = [str(raw_text).strip()]
    scored = []
    for i, chunk in enumerate(chunks):
        lower = chunk.lower()
        score = sum(3 for token in tokens if re.search(rf"\b{re.escape(token)}\b", lower))
        if re.search(r"https?://|\bportal\b|\blogin\b", lower):
            score += 3
        if re.search(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b", chunk):
            score += 2
        if re.search(r"\b(?:rs\.?|inr)\s*\d+", lower):
            score += 2
        if score:
            scored.append((-score, i, chunk))
    scored.sort()
    selected = []
    seen = set()
    for _, _, chunk in scored:
        clean = " ".join(chunk.split())
        if clean[:60] in seen:
            continue
        seen.add(clean[:60])
        if len(clean) > max_chars:
            clean = clean[:max_chars].rsplit(" ", 1)[0].rstrip() + "…"
        selected.append(clean)
        if len(selected) >= max_snippets:
            break
    return selected


def _document_year_matches(record, year):
    """Match notice identity, not an incidental historical/publication year."""
    return matches_identity_year(record, year)


def _lexical_score(question, record):
    """Field-weighted exact-token score (BM25-inspired, not true BM25)."""
    data = record.get("structured_data") or {}
    title = " ".join(str(value or "") for value in (
        record.get("title"), data.get("title"), data.get("target_audience"),
    )).lower()
    summary = str(data.get("summary") or "").lower()
    key_points = " ".join(map(str, data.get("key_points") or [])).lower()
    raw = str(record.get("raw_text") or "")[:1800].lower()
    tokens = set(_tokens(question))
    if not tokens:
        return 0.0
    score = 0.0
    for token in tokens:
        pattern = rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])"
        if re.search(pattern, title):
            score += 4
        if re.search(pattern, summary):
            score += 2
        if re.search(pattern, key_points):
            score += 2
        if re.search(pattern, raw):
            score += 0.5
    # A query's adjacent meaningful phrase helps when titles are very similar.
    cleaned = [token for token in _tokens(question) if not token.isdigit()]
    for a, b in zip(cleaned, cleaned[1:]):
        phrase = a + " " + b
        if phrase in title:
            score += 2
    return score


def retrieve_time_based(question, top_k=3):
    """Get most recent notices by *official issue date* in Asia/Kolkata."""
    now = datetime.now(INDIA_TZ)
    text = str(question or "").lower()
    year = extract_year_from_question(question)
    if year is not None and not re.search(r"\b(?:today|yesterday)\b", text):
        # "Latest notices for 2026-27" is a session identity constraint,
        # not an issue-date=2026 filter.
        return retrieve_filtered_notices(question, top_k=top_k, sort_latest=True)
    records = list(notices_collection.find({"status": "processed"}))
    if "today" in text or "today's" in text:
        target = now.date()
        records = [r for r in records if official_issue_date(r) == target]
    elif "yesterday" in text:
        target = now.date() - timedelta(days=1)
        records = [r for r in records if official_issue_date(r) == target]
    elif year is not None:
        records = [r for r in records if (official_issue_date(r) or date.min).year == year]
    records.sort(key=parse_issue_date, reverse=True)
    return records[:max(0, int(top_k))]


def retrieve_topic_notices(topic, top_k=3):
    """Find topic-specific notices and sort chronologically (for 'latest WBJEE')."""
    term = str(topic or "").strip()
    if not term:
        return []
    wanted = max(0, int(top_k))
    if wanted == 0:
        return []
    aliases = TOPIC_ALIASES.get(term.lower(), (term,))
    pattern = re.compile("|".join(rf"\b{re.escape(alias)}\b" for alias in aliases), re.I)
    title_query = {
        "status": "processed",
        "$or": [{"structured_data.title": pattern}, {"title": pattern}],
    }
    records = list(notices_collection.find(title_query))
    if len(records) < wanted:
        existing_ids = [r["_id"] for r in records if "_id" in r]
        body_query = {
            "status": "processed",
            "$or": [
                {"structured_data.target_audience": pattern},
                {"structured_data.summary": pattern},
                {"structured_data.key_points": pattern},
                {"raw_text": pattern},
            ],
        }
        if existing_ids:
            body_query["_id"] = {"$nin": existing_ids}
        records.extend(notices_collection.find(body_query))
    if term.lower() in TOPIC_ALIASES:
        matches = [r for r in records if _topic_matches(r, {term.lower()})]
        if matches:
            records = matches
    records.sort(key=parse_issue_date, reverse=True)
    seen = set()
    result = []
    for record in records:
        nid = record.get("notice_id") or record.get("_id")
        if nid in seen:
            continue
        seen.add(nid)
        result.append(record)
        if len(result) >= wanted:
            break
    return result


def _get_hit_value(hit, key, default=None):
    return hit.get(key, default) if isinstance(hit, dict) else getattr(hit, key, default)


def _get_hits(results):
    result = _get_hit_value(results, "result", {})
    return _get_hit_value(result, "hits", []) or []


def retrieve_semantic(question, top_k=5):
    """Hybrid Pinecone+Mongo ranking: dense/lexical RRF + explicit scope.

    One MongoDB batch read replaces the previous Pinecone-hit N+1 find_one loop.
    Specific notice topics/rounds/dates become scope constraints only when
    matching candidates actually exist; otherwise we return a ranked fallback.
    """
    top_k = max(0, int(top_k))
    if not question or top_k == 0:
        return []

    year = extract_year_from_question(question)
    sessions = academic_sessions(question)
    # A comparison needs two separately scoped retrievals.
    if len(sessions) > 1:
        return []
    session = requested_session(question)
    topics = _explicit_topics(question)
    rounds = _requested_rounds(question)
    issue_date = _explicit_issue_date(question)
    # Keep bounded remote vector retrieval even if the caller requests many.
    candidate_k = min(max(30, top_k * 4), 80)

    def pinecone_search(filter_dict=None):
        try:
            params = {"inputs": {"text": question}, "top_k": candidate_k}
            if filter_dict:
                params["filter"] = filter_dict
            result = index.search_records(namespace=NAMESPACE, query=params)
            return _get_hits(result)
        except Exception as exc:
            print(f"[UniAI] Pinecone search error: {exc}")
            return []

    # Preserve existing optional year metadata filtering, but search broadly if
    # too few hits were found (metadata may be absent on older indexed notices).
    hits = pinecone_search({"year": {"$eq": year}}) if year is not None else pinecone_search()
    if year is not None and len(hits) < min(10, candidate_k):
        broad_hits = pinecone_search()
        ids = {_get_hit_value(h, "_id") or _get_hit_value(h, "id") for h in hits}
        for hit in broad_hits:
            hit_id = _get_hit_value(hit, "_id") or _get_hit_value(hit, "id")
            if hit_id and hit_id not in ids:
                hits.append(hit)
                ids.add(hit_id)

    dense_ranks = {}
    for hit in hits:
        nid = _get_hit_value(hit, "_id") or _get_hit_value(hit, "id")
        if nid and nid not in dense_ranks:
            dense_ranks[nid] = len(dense_ranks) + 1

    # Bulk fetch all vector hits, keeping MongoDB status restrictions intact.
    records_by_id = {}
    if dense_ranks:
        cursor = notices_collection.find({
            "notice_id": {"$in": list(dense_ranks)}, "status": "processed",
        })
        for record in cursor:
            nid = record.get("notice_id")
            # During revision re-extraction, an older Pinecone vector may
            # still exist. Do not rank it until the new content is indexed.
            if nid and record.get("pinecone_indexed") is not False:
                records_by_id[nid] = record

    # Optional lexical discovery: use identifiers first, not arbitrary set order.
    key_terms = []
    for topic in sorted(topics):
        key_terms.extend(TOPIC_ALIASES[topic])
    key_terms.extend(t for t in _tokens(question)
                     if not t.isdigit() and t not in key_terms)
    key_terms = list(dict.fromkeys(key_terms))[:5]
    if key_terms:
        pattern = re.compile("|".join(rf"\b{re.escape(t)}\b" for t in key_terms), re.I)
        cursor = notices_collection.find({
            "status": "processed",
            "$or": [
                {"title": pattern},
                {"structured_data.title": pattern},
                {"structured_data.target_audience": pattern},
                {"structured_data.summary": pattern},
            ],
        }).limit(35)
        for record in cursor:
            nid = record.get("notice_id")
            if nid and nid not in records_by_id:
                records_by_id[nid] = record

    if not records_by_id:
        return []

    candidates = list(records_by_id.values())
    # Candidate-set scoping: exclude clear competitors when relevant evidence is
    # present. This ensures JECA cannot displace WBJEE in a WBJEE-specific query.
    if topics:
        topical = [r for r in candidates if _topic_matches(r, topics)]
        if topical:
            candidates = topical
    # Never return a different academic session or year if the requested
    # one has no hits; a vector similarity score cannot override identity.
    if session is not None:
        candidates = [r for r in candidates if matches_session(r, session)]
        if not candidates:
            return []
    elif year is not None:
        candidates = [r for r in candidates if _document_year_matches(r, year)]
        if not candidates:
            return []
    if issue_date is not None:
        candidates = [r for r in candidates if official_issue_date(r) == issue_date]
        if not candidates:
            return []
    if rounds:
        round_matches = [r for r in candidates if _record_rounds(r) & rounds]
        if round_matches:
            candidates = round_matches

    lexical = {r["notice_id"]: _lexical_score(question, r) for r in candidates}
    positive_sparse = sorted(
        (r for r in candidates if lexical[r["notice_id"]] > 0),
        key=lambda r: (-lexical[r["notice_id"]], str(r["notice_id"])),
    )
    sparse_ranks = {r["notice_id"]: i for i, r in enumerate(positive_sparse, 1)}
    now = datetime.now(INDIA_TZ)
    ranked = []
    for record in candidates:
        nid = record["notice_id"]
        score = 0.0
        if nid in dense_ranks:
            score += 1 / (60 + dense_ranks[nid])
        if nid in sparse_ranks:
            score += 1 / (60 + sparse_ranks[nid])
        # Preserve explicit subject / round precision without repeating a broad
        # recency boost for historical admission questions.
        if topics and _topic_matches(record, topics):
            score *= 1.20
        if rounds and _record_rounds(record) & rounds:
            score *= 1.20
        if issue_date and official_issue_date(record) == issue_date:
            score *= 1.40
        if year is None and not issue_date:
            days = max(0, (now - parse_issue_date(record)).days)
            score *= math.exp(-0.00035 * days)
        ranked.append((record, score))
    ranked.sort(key=lambda item: (-item[1], -parse_issue_date(item[0]).toordinal(),
                                  str(item[0].get("notice_id"))))

    if DEBUG():
        print(f"[UniAI Hybrid] Candidates={len(records_by_id)}, scoped={len(candidates)}; "
              f"year={year}, session={session}, topics={sorted(topics)}, rounds={sorted(rounds)}, "
              f"notice_date={issue_date}; query={question!r}")
        for rank, (record, score) in enumerate(ranked[:5], 1):
            print(f"  #{rank} score={score:.5f} "
                  f"date={parse_issue_date(record):%d-%m-%Y} "
                  f"title={record.get('title', '')}")
    return [record for record, _ in ranked[:top_k]]


def retrieve_context(question, top_k=3):
    """Route pure time requests chronologically and named topics by exact scope."""
    if is_pure_time_query(question):
        return retrieve_time_based(question, top_k)
    if (detect_search_topics(question) or _requested_issue_date_any_position(question)
            or extract_year_from_question(question) is not None):
        return retrieve_filtered_notices(
            question, top_k,
            sort_latest=bool(re.search(r"\b(?:latest|recent|most\s+recent)\b",
                                       str(question or ""), re.I)),
        )
    return retrieve_semantic(question, top_k)


def build_context_string(records, question=None):
    """Preserve Phase 2 evidence-context format and public function signature."""
    if not records:
        return "No relevant notices were found."
    context_blocks = []
    for idx, record in enumerate(records, 1):
        sd = record.get("structured_data") or {}
        title = sd.get("title") or record.get("title") or "Untitled Notice"
        notice_type = sd.get("notice_type") or "General"
        issue_date = sd.get("issue_date") or "Not specified"
        ref_no = sd.get("reference_no") or "Not specified"
        audience = sd.get("target_audience") or "All Students"
        summary = sd.get("summary") or "No summary available."
        action = sd.get("action_required")
        dates = sd.get("important_dates") or {}
        fees = sd.get("fees") or {}
        points = sd.get("key_points") or []
        url = record.get("url") or "Not available"
        block = [
            f"[NOTICE #{idx}]", f"Title: {title}",
            f"Type: {notice_type} | Issue Date: {issue_date} | Reference No: {ref_no}",
            f"Target Audience: {audience}", f"Summary: {summary}",
        ]
        date_info = []
        if dates.get("start_date"):
            date_info.append(f"Start Date: {dates['start_date']}")
        if dates.get("last_date"):
            date_info.append(f"Last/Closing Date: {dates['last_date']}")
        if date_info:
            block.append("Important Dates: " + " | ".join(date_info))
        if fees.get("amount") is not None:
            fee_type = fees.get("type")
            label = f"{fee_type.capitalize()} fee" if fee_type else "Fee (unspecified type)"
            block.append(f"{label}: {fees['amount']} {fees.get('currency') or ''}".strip())
        if action:
            block.append(f"Action Required: {action}")
        if points:
            block.append("Key Points:\n" + "\n".join(f" - {point}" for point in points))
        documents = sd.get("required_documents") or []
        if documents:
            block.append("Required Documents (extracted):\n" +
                         "\n".join(f" - {doc}" for doc in documents if doc))
        raw = record.get("raw_text") or ""
        if raw and question:
            snippets = extract_relevant_snippets(raw, question,
                                                 max_snippets=2, max_chars=400)
            if snippets:
                block.append("Official Circular Excerpts:\n" +
                             "\n".join(f' > "{s}"' for s in snippets))
        block.append(f"Official Source URL: {url}")
        context_blocks.append("\n".join(block))
    return "\n\n" + ("=" * 45) + "\n\n".join(context_blocks) + "\n" + ("=" * 45)

# ---------------------------------------------------------------------------
# Phase 6 reliability: explicit-scope MongoDB retrieval for named notice topics
# ---------------------------------------------------------------------------
# A campus notice collection is small enough to search the primary metadata.
# Avoid asking a vector model to decide whether a WBJEE/JECA/year constraint
# applies. Integrated Pinecone search remains available through retrieve_semantic.

SEARCH_TOPICS = {
    "wbjee": ("wbjee", "wbjeeb"),
    "jeca": ("jeca",),
    "jelet": ("jelet",),
    "jemat": ("jemat", "wbjemat"),
    "pget": ("pget",),
    "cet": ("cet",),
    "hostel": ("hostel", "hostels"),
    "holiday": ("holiday", "holidays", "puja", "vacation"),
    "registration": ("registration", "register", "enrolment", "enrollment"),
    "frams": ("frams", "u-frams", "u‑frams", "face registration"),
    "scholarship": ("scholarship", "scholarships", "fellowship"),
    "exam": ("exam", "examination", "examinations", "semester", "routine"),
    "placement": ("placement", "placements", "recruitment", "training and placement"),
    "ragging": ("ragging", "discipline", "disciplinary"),
    "vacant": ("vacant", "vacancy", "vacancies", "decentralised", "decentralized"),
    "affiliation": ("affiliation", "affiliated", "non-aicte"),
}


def _phrase_regex(words):
    return re.compile("|".join(
        rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])" for word in words
    ), re.I)


def detect_search_topics(question):
    """Return explicitly named subject categories, not guessed intent."""
    lower = str(question or "").casefold()
    found = set()
    for topic, aliases in SEARCH_TOPICS.items():
        if _phrase_regex(aliases).search(lower):
            found.add(topic)
    # 'face registration' is more specific than generic registration.
    if "frams" in found:
        found.discard("registration")
    # Hostel closure during Durga Puja: holiday is context, hostel is subject.
    if "hostel" in found:
        found.discard("holiday")
    # In 'guaranteed placement salary in the WBJEE notice', placement
    # describes the requested fact, not a second notice topic.
    if (found & set(ADMISSION_TOPICS) and "placement" in found
            and re.search(r"\b(?:salary|package|pay|amount|lpa)\b", lower)):
        found.discard("placement")
    # WBJEE portal registration means WBJEE is the primary topic.
    if found & {"wbjee", "jeca", "jelet", "jemat", "pget", "cet"}:
        found.discard("registration")
    return found


def _primary_search_text(record):
    sd = record.get("structured_data") or {}
    return " ".join(str(x or "") for x in (
        record.get("title"), sd.get("title"), sd.get("target_audience"),
        sd.get("notice_type"),
    )).casefold()


def _secondary_search_text(record):
    sd = record.get("structured_data") or {}
    return " ".join(str(x or "") for x in (
        sd.get("summary"), sd.get("action_required"), sd.get("key_points"),
    )).casefold()


def _exam_topics_in_text(text):
    """Exams explicitly named in one identity field, not incidental OCR text."""
    return {
        exam for exam in ADMISSION_TOPICS
        if _phrase_regex(SEARCH_TOPICS[exam]).search(str(text or "").casefold())
    }


def _search_topic_matches(record, topics):
    if not topics:
        return True
    sd = record.get("structured_data") or {}
    primary = _primary_search_text(record)
    secondary = _secondary_search_text(record)

    # The student-visible title is authoritative for subject identity. In
    # real Mongo records the website title, generated structured title and
    # target_audience sometimes DISAGREE: for example, a JELET title can have
    # a WBJEEB board reference in target_audience. Combining all three into
    # one bag of words used to let that JELET notice match a WBJEE search.
    requested_exams = set(ADMISSION_TOPICS) & set(topics)
    if requested_exams:
        extracted_title = sd.get("title") or ""
        scraped_title = record.get("title") or ""
        # A conflicting exam in EITHER title vetoes the document. Do not
        # allow a mention of WBJEE in its audience/summary to override JELET.
        # Joint-exam titles (JECA and JELET) remain eligible for either query.
        for title in (extracted_title, scraped_title):
            title_exams = _exam_topics_in_text(title)
            if title_exams and not (title_exams & requested_exams):
                return False

        identity_exams = (
            _exam_topics_in_text(extracted_title)
            | _exam_topics_in_text(scraped_title)
        )
        if identity_exams:
            return bool(identity_exams & requested_exams)

        # No exam named in either title. JELET and JECA are distinct entrance
        # exams and cannot be inferred from generic B.Tech/MCA lateral
        # registration notices: the notice must name that entrance exam in
        # its title or have an unambiguous exam-specific target audience.
        audience_exams = _exam_topics_in_text(sd.get("target_audience"))
        if requested_exams & {"jelet", "jeca"}:
            return bool(audience_exams & requested_exams)
        if audience_exams:
            return bool(audience_exams & requested_exams)
        return any(
            _phrase_regex(SEARCH_TOPICS[exam]).search(secondary)
            for exam in requested_exams
        )

    # These subjects must actually be THE notice's subject. Previously a
    # mention of "hostel" in an anti-ragging committee's key points, or of
    # "scholarship" in a refund notice, polluted a latest-notice list.
    title = " ".join(str(v or "") for v in (
        record.get("title"), sd.get("title")
    )).casefold()
    title_scoped = {"hostel", "scholarship", "holiday", "exam"}
    for topic in topics & title_scoped:
        if topic == "hostel" and not re.search(r"\bhostels?\b", title):
            return False
        if topic == "scholarship" and not re.search(
            r"\b(?:scholarships?|fellowships?|doctoral\s+fellowship|"
            r"stipends?|financial\s+assistance)\b", title
        ):
            return False
        if topic == "holiday" and not re.search(
            r"\b(?:holidays?|puja|vacations?|closure|closed)\b", title
        ):
            return False
        if topic == "exam" and not re.search(
            r"\b(?:exams?|examinations?|semester|routines?|timetables?|"
            r"time[ -]?tables?|schedule|programme|program)\b", title
        ):
            return False
    # A query naming several subjects should not be satisfied by a single
    # incidental mention of only one of them.
    return all(
        _phrase_regex(SEARCH_TOPICS[topic]).search(primary)
        or (topic not in title_scoped
            and _phrase_regex(SEARCH_TOPICS[topic]).search(secondary))
        for topic in topics
    )


def _question_scope_matches(question, record):
    """Require subject-specific relevance beyond a generic category word.

    This deliberately narrows searches for registration of students, holiday
    notices, placement/recruitment notices and verification-specific WBJEE
    queries. It never invents a document when none fits the requested scope.
    """
    q = str(question or "").casefold()
    sd = record.get("structured_data") or {}
    primary = " ".join(str(x or "") for x in (
        record.get("title"), sd.get("title"),
    )).casefold()
    secondary = " ".join(str(x or "") for x in (
        sd.get("summary"), sd.get("action_required"),
    )).casefold()
    text = primary + " " + secondary
    # JELET-2025 issue-date and eligibility questions must identify a
    # JELET-specific circular, not the issue date of an unrelated generic
    # lateral-registration notice that lists JELET among its audiences.
    if re.search(r"\bjelet\b", q) and re.search(
        r"\b(?:issue\s+date|date\s+of\s+issue|issued|eligib|criteria)\w*\b", q
    ) and not re.search(r"\bjelet\b", primary):
        return False
    # A request for student-registration notices is NOT a search for any
    # document that happens to say "registering students" in its summary.
    # First require that student registration is the actual notice subject.
    if re.search(r"\bregistration\s+of\s+students?\b|\bstudents?\s+registration\b", q):
        excluded_subject = (
            r"\b(?:conference|affiliat(?:ion|ing)|new\s+colleges?|"
            r"supernumerary|vacant\s+seats?|seat\s+(?:intake|allotment)|"
            r"recruitment|scholarship|fellowship)\b"
        )
        if re.search(excluded_subject, primary):
            return False
        if not re.search(r"\b(?:registration|registrations|enrolment|enrollment|"
                         r"registering|registration\s+portal)\b", primary):
            return False
        if not re.search(r"\b(?:students?|admitted|allotted|admissions?|"
                         r"registration\s+portal)\b", text):
            return False

    if re.search(r"\bholidays?\b", q):
        if not re.search(r"\b(?:holidays?|puja|vacation|hostel\s+clos(?:ure|ed)|campus\s+clos(?:ure|ed))\b", primary):
            return False
    # A generic admission *notice* is about admissions, not hostel seats or
    # a refund circular. Fee questions for a named hostel notice are unaffected.
    if re.search(r"\b(?:admission\s+notices?|admissions?\s+circular)\b", q):
        if not re.search(r"\badmissions?\b", primary):
            return False
        if re.search(r"\b(?:hostels?|accommodat|ragging)\b", primary):
            return False
        if re.search(r"\b(?:refund|withdrawal|cancellation)\b", primary) and not re.search(
            r"\b(?:refund|withdrawal|cancellation)\b", q
        ):
            return False
    # A question about placement salary *within a WBJEE notice* is
    # a requested fact, not a search for recruitment announcements.
    placement_as_field = bool(
        re.search(r"\b(?:salary|package|lpa)\b", q)
        and set(detect_search_topics(question)) & set(ADMISSION_TOPICS)
    )
    if re.search(r"\b(?:placements?|recruitment)\b", q) and not placement_as_field:
        if not re.search(r"\b(?:placements?|recruitment|campus\s+drives?|career\s+fair|training\s+and\s+placement|tpo)\b", primary):
            return False
    if re.search(r"\b(?:document\s+verification|verification\s+and\s+admission)\b", q):
        if not re.search(r"\b(?:verification|allottees?|counselling|counseling|admission\s+reporting)\b", primary):
            return False

    # When an entrance-exam query specifically asks for admission or
    # counselling, exclude *registration-only* circulars that happen to
    # mention that exam. An admission/reporting schedule still qualifies.
    exam_requested = bool(set(detect_search_topics(question)) & set(ADMISSION_TOPICS))
    if exam_requested and re.search(r"\b(?:admission|counselling|counseling)\b", q):
        if re.search(r"\bregistration\b", primary) and not re.search(
                r"\b(?:admission|counselling|counseling|reporting)\b", primary):
            return False

    # A general examination routine search must not return an unrelated
    # PhD RPE *course* schedule. Explicit RPE/PhD queries are still allowed.
    if re.search(r"\b(?:routines?|time[ -]?tables?|exam(?:ination)?\s+schedules?)\b", q):
        if not re.search(
            r"\b(?:routines?|time[ -]?tables?|exam(?:ination)?\s+schedules?|"
            r"examination\s+programmes?|exam\s+programmes?)\b", primary
        ):
            return False
        if not re.search(r"\b(?:phd|ph\.d\.?|rpe|research\s+scholars?)\b", q):
            if re.search(r"\b(?:phd|ph\.d\.?|rpe|research\s+scholars?)\b", primary):
                return False
    elif (re.search(r"\b(?:exam|examination|semester)\b", q)
            and re.search(r"\bschedules?\b", q)):
        if not re.search(r"\b(?:schedules?|routines?|timetables?|exam\s+programmes?)\b", primary):
            return False
    # A general admission-reporting question must target reporting,
    # not a portal closure that only mentions admission in its body.
    if re.search(r"\badmission\s+reporting\b|\breporting\s+instructions?\b", q):
        if not re.search(r"\b(?:report(?:ing)?|physical\s+verification|"
                         r"document\s+verification|allottees?)\b", primary):
            return False
    # "Durga Puja" and "Viswakarma Puja" are distinct holidays. Hard
    # festival identity prevents plausible-looking but unrelated citations.
    if re.search(r"\bdurga\s+puja\b", q):
        if not re.search(r"\bdurga\s+puja\b", primary):
            return False
    # Do not replace a hostel *closure* circular with an allotment notice.
    if re.search(r"\bhostels?\s+clos(?:ure|ing|ed)\b", q):
        if not re.search(r"\bhostels?\b", primary) or not re.search(
            r"\b(?:closure|closing|closed|vacate)\b", primary
        ):
            return False
    # University holiday ≠ hostel closure, even when both involve Durga Puja.
    if re.search(r"\b(?:university|academic|official)\s+holidays?\b", q):
        if re.search(r"\bhostels?\b", primary):
            return False
        if not re.search(r"\b(?:holidays?|vacation|holiday\s+list|"
                         r"university\s+closure)\b", primary):
            return False

    # Recruitment searches should not substitute staff appointment orders for
    # placement opportunities unless the user explicitly asks about officers.
    if (re.search(r"\b(?:placements?|recruitment)\b", q)
            and not re.search(r"\b(?:officer|appointment|staff|tpo)\b", q)):
        if re.search(r"\bappointment\s+of\b.*\b(?:placement|training)\b.*\bofficer\b", primary):
            return False
    return True


def enforce_source_scope(question, records):
    """Final safeguard: a source-bearing answer must satisfy explicit topic
    and subject constraints even if another retrieval entry point is used.

    This catches regressions where Pinecone results or a different router
    bypass strict Mongo filtering. Never replace excluded documents with
    loosely related PDFs: missing verified matches is safer.
    """
    topics = detect_search_topics(question)
    kept = []
    for record in records:
        if not isinstance(record, dict):
            continue
        if topics and not _search_topic_matches(record, topics):
            continue
        if not _question_scope_matches(question, record):
            continue
        kept.append(record)
    return kept


def _year_scope_matches(record, year):
    """Use the official notice identity, never a session's ending year."""
    return matches_identity_year(record, year)


def _requested_issue_date_any_position(question):
    """Only interpret a calendar date as issue date when explicitly requested."""
    lower = str(question or "").lower()
    if not re.search(r"\b(?:issued|published|dated)\s+on\b|\bnotices?\s+(?:of|from)\s+\d", lower):
        return None
    match = re.search(r"\b(\d{1,2})\s+(" +
        "|".join(MONTH_NUMBERS) + r")\s+(20\d{2})\b", lower)
    if match:
        day, month, year = match.groups()
        try:
            return date(int(year), MONTH_NUMBERS[month], int(day))
        except ValueError:
            return None
    for pattern, fmt in ((r"\b\d{1,2}-\d{1,2}-20\d{2}\b", "%d-%m-%Y"),
                         (r"\b\d{1,2}/\d{1,2}/20\d{2}\b", "%d/%m/%Y"),
                         (r"\b20\d{2}-\d{1,2}-\d{1,2}\b", "%Y-%m-%d")):
        m = re.search(pattern, lower)
        if m:
            try:
                return datetime.strptime(m.group(0), fmt).date()
            except ValueError:
                return None
    return None


def _notice_search_score(question, record):
    text = str(question or "").casefold()
    # Terms that describe query intent add no distinctive value.
    ignore = {"find", "show", "give", "tell", "about", "notices", "notice",
              "the", "of", "for", "in", "from", "which", "are", "there",
              "and", "or", "students", "student", "any", "university",
              "makaut", "latest", "recent", "what", "is", "with", "do",
              "details", "2025", "2026", "2027", "published", "issued"}
    tokens = [t for t in _tokens(text) if t not in ignore and not t.isdigit()]
    primary = _primary_search_text(record)
    secondary = _secondary_search_text(record)
    score = 0.0
    for token in tokens:
        pat = rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])"
        if re.search(pat, primary):
            score += 6.0
        elif re.search(pat, secondary):
            score += 2.0
    return score


def retrieve_filtered_notices(question, top_k=5, *, force_year=None,
                              sort_latest=False, issue_date=None):
    """Find notices with strict topic/year/date constraints; never substitute others.

    Uses MongoDB's indexed status filter and a bounded result set. A targeted
    search intentionally does not use a broad Pinecone fallback because that
    can return a confident answer from a different exam/year/topic.
    """
    wanted = max(0, min(20, int(top_k)))
    if not wanted:
        return []
    topics = detect_search_topics(question)
    year = force_year if force_year is not None else extract_year_from_question(question)
    sessions = academic_sessions(question)
    session = requested_session(question, force_year=force_year)
    # Multiple academic sessions are a comparison, not one unqualified target.
    # A forced year must identify the matching session's *starting* year.
    if (len(sessions) > 1 and session is None) or (
        force_year is not None and sessions and session is None
    ):
        return []
    target_date = issue_date or _requested_issue_date_any_position(question)
    # A date request is narrower than a year request. Its calendar date is
    # already checked against the official issue_date.
    records = notices_collection.find({"status": "processed"})
    selected = []
    for record in records:
        if topics and not _search_topic_matches(record, topics):
            continue
        if not _question_scope_matches(question, record):
            continue
        if session is not None and not matches_session(record, session):
            continue
        if target_date is not None and official_issue_date(record) != target_date:
            continue
        issued_year_request = bool(re.search(
            r"\b(?:issued|published|dated)\s+in\s+20\d{2}\b",
            str(question or ""), re.I,
        ))
        if target_date is None and year is not None:
            year_ok = ((official_issue_date(record) or date.min).year == year if issued_year_request
                       else True if session is not None
                       else _year_scope_matches(record, year))
            if not year_ok:
                continue
        selected.append(record)
    if sort_latest or target_date is not None:
        selected.sort(key=lambda r: (parse_issue_date(r), _notice_search_score(question, r)), reverse=True)
    else:
        selected.sort(key=lambda r: (_notice_search_score(question, r),
                                     parse_issue_date(r)), reverse=True)
    seen = set()
    filtered = []
    for record in selected:
        identity = str(record.get("notice_id") or record.get("_id") or "")
        if identity in seen:
            continue
        seen.add(identity)
        filtered.append(record)
        if len(filtered) >= wanted:
            break
    if DEBUG():
        print(f"[UniAI Retrieval] matched={len(selected)} selected={len(filtered)} "
              f"topics={sorted(topics)} year={year} session={session} issue_date={target_date} "
              f"query={question!r}", flush=True)
    return filtered
