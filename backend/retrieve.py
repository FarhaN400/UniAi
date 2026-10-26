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
    """Prefer structured official issue_date, falling back to scrape timestamp."""
    sd = record.get("structured_data") or {}
    value = sd.get("issue_date")
    if isinstance(value, datetime):
        return normalize_datetime(value)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=INDIA_TZ)
    if value:
        for fmt in ("%d-%m-%Y", "%d-%m-%Y %H:%M", "%Y-%m-%d",
                    "%d/%m/%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(str(value).strip(), fmt).replace(tzinfo=INDIA_TZ)
            except ValueError:
                pass
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
    if year is None:
        return True
    data = record.get("structured_data") or {}
    # The notice's identifying fields carry more authority than incidental years
    # mentioned in government circular numbers or historical references.
    identifying = " ".join(str(value or "") for value in (
        record.get("title"), data.get("title"), data.get("issue_date"),
        data.get("academic_year"), data.get("target_audience"),
    ))
    if re.search(rf"(?<!\d){year}(?!\d)", identifying):
        return True
    # Some older notices have the year only in summary / body.
    other = " ".join(str(value or "") for value in (
        data.get("summary"), data.get("key_points"),
        str(record.get("raw_text") or "")[:2000],
    ))
    return bool(re.search(rf"(?<!\d){year}(?!\d)", other))


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
    records = list(notices_collection.find({"status": "processed"}))
    if "today" in text or "today's" in text:
        target = now.date()
        records = [r for r in records if parse_issue_date(r).date() == target]
    elif "yesterday" in text:
        target = now.date() - timedelta(days=1)
        records = [r for r in records if parse_issue_date(r).date() == target]
    elif year is not None:
        records = [r for r in records if parse_issue_date(r).year == year]
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
            if nid:
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
    if year is not None:
        same_year = [r for r in candidates if _document_year_matches(r, year)]
        if same_year:
            candidates = same_year
    if issue_date is not None:
        dated = [r for r in candidates if parse_issue_date(r).date() == issue_date]
        if dated:
            candidates = dated
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
        if issue_date and parse_issue_date(record).date() == issue_date:
            score *= 1.40
        if year is None and not issue_date:
            days = max(0, (now - parse_issue_date(record)).days)
            score *= math.exp(-0.00035 * days)
        ranked.append((record, score))
    ranked.sort(key=lambda item: (-item[1], -parse_issue_date(item[0]).toordinal(),
                                  str(item[0].get("notice_id"))))

    if DEBUG():
        print(f"[UniAI Hybrid] Candidates={len(records_by_id)}, scoped={len(candidates)}; "
              f"year={year}, topics={sorted(topics)}, rounds={sorted(rounds)}, "
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
    if detect_search_topics(question) or _requested_issue_date_any_position(question):
        return retrieve_filtered_notices(question, top_k)
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

        # No exam named in either title. Audience can establish identity,
        # but not if it identifies a different exam; else use summary.
        audience_exams = _exam_topics_in_text(sd.get("target_audience"))
        if audience_exams:
            return bool(audience_exams & requested_exams)
        return any(
            _phrase_regex(SEARCH_TOPICS[exam]).search(secondary)
            for exam in requested_exams
        )

    # Non-exam topic matching keeps the existing broader semantics.
    return any(_phrase_regex(SEARCH_TOPICS[topic]).search(primary)
               for topic in topics) or any(
        _phrase_regex(SEARCH_TOPICS[topic]).search(secondary)
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

        # For an explicitly requested *academic session*, require that very
        # session. Merely containing 2026 in "2025-2026" is not a match for
        # 2026-27; likewise the 2026 issue date does not imply AY 2026-27.
        academic_request = re.search(
            r"\b(?:academic\s+(?:year|session)|ay)\s*"
            r"(20\d{2})\s*[-–—/]\s*(20\d{2}|\d{2})\b", q,
        )
        if academic_request:
            start = int(academic_request.group(1))
            end_text = academic_request.group(2)
            end = int(end_text) if len(end_text) == 4 else (start // 100) * 100 + int(end_text)
            requested_session = (start, end)

            def sessions(value):
                pairs = set()
                for a, b in re.findall(r"\b(20\d{2})\s*[-–—/]\s*(20\d{2}|\d{2})\b", value):
                    begin = int(a)
                    finish = int(b) if len(b) == 4 else (begin // 100) * 100 + int(b)
                    pairs.add((begin, finish))
                return pairs

            title_sessions = sessions(primary)
            # The title's session identifies the circular. A different year
            # mentioned in its historical context cannot override the title.
            if title_sessions:
                if requested_session not in title_sessions:
                    return False
            elif requested_session not in sessions(secondary):
                return False
    if re.search(r"\bholidays?\b", q):
        if not re.search(r"\b(?:holidays?|puja|vacation|hostel\s+clos(?:ure|ed)|campus\s+clos(?:ure|ed))\b", primary):
            return False
    if re.search(r"\b(?:placements?|recruitment)\b", q):
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

    # Requests explicitly for exam *schedules* should not be satisfied by fee
    # waivers or administrative documents merely using the word examination.
    if (re.search(r"\b(?:exam|examination|semester)\b", q)
            and re.search(r"\bschedules?\b", q)):
        if not re.search(r"\b(?:schedules?|routines?|timetables?|dates?|programmes?|programs?)\b", primary):
            return False

    # Recruitment searches should not substitute staff appointment orders for
    # placement opportunities unless the user explicitly asks about officers.
    if (re.search(r"\b(?:placements?|recruitment)\b", q)
            and not re.search(r"\b(?:officer|appointment|staff|tpo)\b", q)):
        if re.search(r"\bappointment\s+of\b.*\b(?:placement|training)\b.*\bofficer\b", primary):
            return False
    return True


def _year_scope_matches(record, year):
    """Use the student-visible notice title as the primary year identity.

    Inconsistent scraped/extracted titles must not enable a JELET-2025 notice
    to satisfy a WBJEE-2026 search solely because its upload/issue date is in
    2026 or another title field mentions 2026.
    """
    if year is None:
        return True
    sd = record.get("structured_data") or {}
    for title in (sd.get("title"), record.get("title")):
        title_years = set(int(y) for y in re.findall(r"\b20\d{2}\b", str(title or "")))
        if title_years:
            return year in title_years
    summary = " ".join(str(x or "") for x in (
        sd.get("summary"), sd.get("target_audience"), sd.get("key_points")
    ))
    summary_years = set(int(y) for y in re.findall(r"\b20\d{2}\b", summary))
    if summary_years:
        return year in summary_years
    return parse_issue_date(record).year == year


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
        if target_date is not None and parse_issue_date(record).date() != target_date:
            continue
        issued_year_request = bool(re.search(
            r"\b(?:issued|published|dated)\s+in\s+20\d{2}\b",
            str(question or ""), re.I,
        ))
        if target_date is None and year is not None:
            year_ok = (parse_issue_date(record).year == year if issued_year_request
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
              f"topics={sorted(topics)} year={year} issue_date={target_date} "
              f"query={question!r}", flush=True)
    return filtered
