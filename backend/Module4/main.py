import os
import sys
import re
import json
from datetime import datetime, date

from langchain_groq import ChatGroq

if __package__:
    from .prompt import rag_prompt
    from .conversation_state import ConversationState
    from .query_understanding import (
        understand_query,
        QueryUnderstandingResult,
        explicitly_changes_notice_topic,
    )
else:
    from prompt import rag_prompt
    from conversation_state import ConversationState
    from query_understanding import (
        understand_query,
        QueryUnderstandingResult,
        explicitly_changes_notice_topic,
    )

# retrieve.py lives in backend/, one level above Module4/
BACKEND_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from retrieve import (
    build_context_string,
    extract_relevant_snippets,
    retrieve_context,
    retrieve_topic_notices,
)

from Module4.evidence import (
    build_evidence_bundle,
    filter_explicit_notice_scope,
    validate_claims,
    missing_amount_guidance,
)


MODEL_NAME = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
NO_RESULTS_MESSAGE = (
    "I could not find this information in the available university notices."
)



# --------------------------------------------------
# Exact notice evidence selection
# --------------------------------------------------

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_DATE_WORDS = (
    r"(?:january|february|march|april|may|june|july|august|"
    r"september|october|november|december)"
)
_NOTICE_STOPWORDS = {
    "explain", "tell", "about", "please", "what", "which", "when",
    "where", "show", "give", "details", "detail", "the", "this",
    "that", "notice", "notification", "dated", "issued", "date",
    "from", "makaut", "university", "official", "and",
    "for", "with", "of", "in", "on", "at", "a", "an", "me",
    "wb", "academic", "session", "course",
    "courses", "2026", "2027", "2025", "2024", "2023",
}


def _date_from_parts(day, month, year):
    try:
        month_number = int(month) if str(month).isdigit() else _MONTHS[str(month).lower()[:3]]
        return date(int(year), month_number, int(day))
    except (ValueError, KeyError, TypeError):
        return None


def extract_explicit_notice_date(question):
    """Return issue date only when the query clearly identifies a dated notice.

    Not used for deadline questions such as 'What is the deadline on 27 Oct?'.
    """
    text = str(question or "").lower()
    marker = re.search(
        r"\b(?:notice|notification|circular|order)\b[^.!?]{0,110}?"
        r"\b(?:dated|issued\s+on|published\s+on|of)\s+",
        text,
    )
    formats = (
        rf"(?P<day>\d{{1,2}})(?:st|nd|rd|th)?[\s-]+(?P<month>{_DATE_WORDS})[\s,/-]+(?P<year>20\d{{2}})",
        r"(?P<day>\d{1,2})[/-](?P<month>\d{1,2})[/-](?P<year>20\d{2})",
        r"(?P<year>20\d{2})[/-](?P<month>\d{1,2})[/-](?P<day>\d{1,2})",
    )
    if marker:
        candidate = text[marker.end():marker.end() + 35]
        for pattern in formats:
            found = re.match(pattern, candidate)
            if found:
                return _date_from_parts(**found.groupdict())
        return None

    for pattern in formats:
        found = re.search(pattern, text)
        if not found:
            continue
        before = text[max(0, found.start() - 45):found.start()]
        after = text[found.end():found.end() + 80]
        if (
            re.search(r"\b(?:notice|notification|circular|order)\b", after)
            and not re.search(r"\b(?:deadline|closing|last\s+date|reporting)\b", before)
        ):
            return _date_from_parts(**found.groupdict())
    return None


def _record_issue_date(record):
    data = record.get("structured_data") or {}
    value = data.get("issue_date")
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    value = value.strip()
    for fmt in ("%d-%m-%Y", "%d-%m-%Y %H:%M", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _notice_topic_tokens(text):
    """Conservative topic terms from a notice-specific query/title."""
    tokens = set(re.findall(r"[a-z]{2,}", str(text or "").lower()))
    # Keep subject acronyms, course names and distinguishing terms.
    return tokens - _NOTICE_STOPWORDS - set(_MONTHS) - {
        "january", "february", "march", "april", "june", "july",
        "august", "september", "october", "november", "december",
    }


def select_notice_evidence(question, records, comparison=False):
    """Choose exact-date evidence before LLM generation.

    Returns (selected_records, had_explicit_notice_date, ambiguous).
    If no candidate matches a requested notice date and title/topic, returns [].
    Comparisons and list queries retain all candidates.
    """
    if comparison:
        return records, False, False
    expected_date = extract_explicit_notice_date(question)
    if expected_date is None:
        return records, False, False

    date_matches = [r for r in records if _record_issue_date(r) == expected_date]
    if not date_matches:
        return [], True, False

    question_terms = _notice_topic_tokens(question)
    scored = []
    for r in date_matches:
        data = r.get("structured_data") or {}
        title = str(data.get("title") or r.get("title") or "")
        title_terms = _notice_topic_tokens(title)
        overlap = len(question_terms & title_terms)
        # A dated query with specific subject terms must not select a same-date,
        # unrelated notice. Exact date by itself is not sufficient.
        scored.append((overlap, r))
    scored.sort(key=lambda item: item[0], reverse=True)

    if question_terms and scored[0][0] == 0:
        return [], True, False
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return [], True, True
    return [scored[0][1]], True, False


def extract_requested_count(question):
    """Extract a user-requested record count from latest/recent notice questions."""
    text = str(question or "").lower()
    if not is_latest_notice_query(text):
        return None

    match = re.search(
        r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b",
        text,
    )
    if not match:
        return None

    count_words = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }
    count_text = match.group(1)
    count = int(count_text) if count_text.isdigit() else count_words[count_text]
    return max(1, min(count, 10))


def is_latest_notice_query(question):
    text = str(question or "").lower()
    return any(
        keyword in text
        for keyword in (
            "latest",
            "recent",
            "new notice",
            "new notices",
            "new notification",
            "new notifications",
        )
    )


def extract_notice_ordinal(question):
    """Extract a requested notice position, such as '5th' or 'fifth one'."""
    text = str(question or "").lower()
    match = re.search(r"\b(\d+)(?:st|nd|rd|th)\b", text)
    if match:
        return max(1, min(int(match.group(1)), 10))

    ordinal_words = {
        "first": 1,
        "second": 2,
        "third": 3,
        "fourth": 4,
        "fifth": 5,
        "sixth": 6,
        "seventh": 7,
        "eighth": 8,
        "ninth": 9,
        "tenth": 10,
    }
    for word, ordinal in ordinal_words.items():
        if re.search(rf"\b{word}\b", text):
            return ordinal
    return None


def extract_supported_topic(question):
    text = str(question or "").lower()
    for topic in ("wbjeeb", "wbjee"):
        if re.search(rf"\b{topic}\b", text):
            return "wbjee"
    return None


def is_latest_topic_notice_query(question):
    text = str(question or "").lower()
    return bool(
        re.search(
            (
                r"\b(?:last|latest|most recent)\s+"
                r"(?:official\s+)?(?:notice|notification|news)\b"
            ),
            text,
        )
    )


def is_single_notice_follow_up(question):
    text = re.sub(r"[?.!,]+$", "", str(question or "").lower().strip())
    pattern = (
        r"(?:(?:please\s+)?(?:give|show|list|send)(?:\s+me)?\s+)?"
        r"(?:(?:just|only)\s+)?(?:one|1)(?:\s+(?:notice|notification|result))?"
    )
    return re.fullmatch(pattern, text) is not None


def is_notice_detail_follow_up(question):
    text = str(question or "").lower()
    detail_requests = (
        "tell me more",
        "more about this",
        "more about that",
        "explain this",
        "explain that",
        "details about this",
        "details about that",
        "what does this notice",
        "what does that notice",
    )
    return any(phrase in text for phrase in detail_requests)


def format_notice_line(record, number=None):
    """Render one notice with a headline and only its essential details."""
    data = record.get("structured_data") or {}
    title = data.get("title") or record.get("title") or "Untitled notice"
    headline = f"{number}. {title}" if number is not None else title
    lines = [headline]

    if data.get("issue_date"):
        lines.append(f"Date: {data['issue_date']}")
    if data.get("reference_no"):
        lines.append(f"Reference: {data['reference_no']}")

    details = data.get("summary") or data.get("action_required")
    if not details and data.get("key_points"):
        details = data["key_points"][0]
    if details:
        details = " ".join(str(details).split())
        # Avoid cutting a notice summary mid-sentence.
        if len(details) > 450:
            prefix = details[:450]
            sentence_ends = list(re.finditer(r"[.!?](?=\s|$)", prefix))
            if sentence_ends and sentence_ends[-1].end() >= 120:
                details = prefix[:sentence_ends[-1].end()]
            else:
                details = prefix.rsplit(" ", 1)[0].rstrip(",;:") + "…"
        lines.append(f"Summary: {details}")

    if record.get("url"):
        lines.append(f"Official source: {record['url']}")

    return "\n".join(lines)


def format_notice_list(records):
    """Render a numbered list with a blank line between notices."""
    return "\n\n".join(
        format_notice_line(record, number=index)
        for index, record in enumerate(records, start=1)
    )



# Production inference runs on Groq, not on a local Ollama server.
# Set GROQ_API_KEY in Render's Environment panel (never commit it).
model = ChatGroq(
    model=MODEL_NAME,
    temperature=0,
    max_tokens=2048,
    max_retries=0,
    timeout=float(os.getenv("UNIAI_GROQ_TIMEOUT", "18")),
)

rag_chain = rag_prompt | model

state = ConversationState()
chat_history = state.chat_history
last_notice_records = state.last_notice_records


def _sync_state():
    """Ensure module-level state and ConversationState instance remain synchronized."""
    global last_notice_records, chat_history
    if last_notice_records is not state.last_notice_records:
        state.set_last_results(last_notice_records)
        if not last_notice_records:
            state.clear_active_notice()
        elif len(last_notice_records) == 1:
            state.set_active_notice(last_notice_records[0])
    if chat_history is not state.chat_history:
        state.chat_history = chat_history


def _sync_back():
    """Sync state lists back to module-level variables."""
    global last_notice_records, chat_history
    if last_notice_records is not state.last_notice_records:
        last_notice_records.clear()
        last_notice_records.extend(state.last_notice_records)
    if chat_history is not state.chat_history:
        chat_history.clear()
        chat_history.extend(state.chat_history)


def _response_text(response):
    """Normalize Ollama/LangChain responses into a JSON-candidate string."""
    content = response.content if hasattr(response, "content") else (
        response.get("content") or response.get("text") or str(response)
        if isinstance(response, dict) else str(response)
    )
    return "".join(str(part) for part in content) if isinstance(content, list) else str(content)


def _record_requires_both_sciences(record):
    """Detect an *explicit* Physics + Mathematics mandatory requirement.

    This is a conservative guard for the common AND-vs-OR error. Do not
    infer requirements for notices that do not establish both subjects.
    """
    data = record.get("structured_data") or {}
    reference_text = (str(data) + " " + str(record.get("raw_text") or "")).casefold()
    patterns = (
        r"\bphysics\s+(?:and|&)\s+(?:mathematics|maths)\b.{0,70}\b(?:mandatory|compulsory|required)\b",
        r"\b(?:mandatory|compulsory|required)\s+(?:courses?|subjects?)\b.{0,320}?\bphysics\s*[,;&]\s*(?:mathematics|maths)\b",
        r"\bphysics\s*[,;&]\s*(?:mathematics|maths)\b.{0,80}\b(?:mandatory|compulsory|required)\b",
    )
    return any(re.search(p, reference_text, re.S) for p in patterns)


def _eligibility_contradiction(statement, record):
    """Return a reason for a narrow, high-confidence eligibility conflict.

    General semantic validation remains outside the scope of this safeguard.
    """
    if not _record_requires_both_sciences(record):
        return None
    lower = statement.casefold()
    if re.search(r"\bphysics\s+(?:or|and/or)\s+(?:mathematics|maths)\b", lower):
        return "Physics or Mathematics contradicts mandatory Physics AND Mathematics"
    if re.search(
        r"\bphysics\s*(?:,|and|&)\s*(?:mathematics|maths)\s*,?\s*or\s+(?:other|any|another|a)\b",
        lower,
    ):
        return "optional subject wording contradicts two compulsory subjects"
    if re.search(r"\b(?:overall|total)\s+(?:class\s*12|12th|10\s*\+\s*2)\s+(?:aggregate|percentage|marks)\b", lower):
        return "overall Class 12 marks are not the specified subject combination"
    if "aggregate" in lower and re.search(r"\b(?:45|40)\s*%", lower):
        if not re.search(r"\b(?:specified|above|these|required|combined|selected)\s+subjects?\b|\bsubject\s+combination\b|\bsubjects?\s+taken\s+together\b", lower):
            return "unqualified aggregate obscures the required subject combination"
    return None


def _apply_eligibility_guard(claims, records_by_id, debug=False):
    """Apply conservative semantic checks after ID/reference validation."""
    kept = []
    for claim in claims:
        notice_id = claim["notice_ids"][0]
        reason = _eligibility_contradiction(claim["text"], records_by_id[notice_id])
        if reason:
            if debug:
                print(f"[UniAI] Eligibility claim rejected: {reason}", flush=True)
            continue
        kept.append(claim)
    return kept


def _missing_notice_overview_facets(question, records_by_id, evidence, claims):
    """Only require overview topics that appear in the selected notice's data.

    This completeness check does not validate facts. Citation validation and
    the separate Physics/Mathematics safeguard run before these checks.
    """
    if len(records_by_id) != 1 or not re.search(
        r"\b(?:explain|summari[sz]e|overview|describe|details)\b", question, re.I
    ):
        return set()
    record = next(iter(records_by_id.values()))
    data = record.get("structured_data") or {}
    title = str(data.get("title") or record.get("title") or "").casefold()
    evidence_text = " ".join(str(item["text"]) for item in evidence.values()).casefold()
    if "vacant" not in title or "b.tech" not in evidence_text:
        return set()

    required = set()
    if all(term in evidence_text for term in (
        "computer science", "information technology", "electronics engineering",
        "industrial engineering",
    )):
        required.add("B.Tech course names")
    if ("physics" in evidence_text
            and ("mathematics" in evidence_text or "maths" in evidence_text)
            and "45" in evidence_text and "40" in evidence_text):
        required.add("eligibility with mandatory subjects and marks")
    dates = data.get("important_dates") or {}
    start_date = str(dates.get("start_date") or "").strip()
    last_date = str(dates.get("last_date") or "").strip()
    if (start_date and last_date and start_date != last_date
            and re.search(r"\b(?:apply|application|applications)\b", evidence_text)):
        required.add("application dates")

    # Demand reporting facts only when one notice field explicitly contains
    # the reporting date and venue; do not hard-code an admission year's date.
    points = data.get("key_points") or []
    if not isinstance(points, (list, tuple)):
        points = [points]
    reporting_points = [
        str(point).casefold() for point in points
        if re.search(r"\b(?:report(?:ing)?|merit list)\b", str(point), re.I)
        and re.search(r"\broom\s*\d+\b", str(point), re.I)
        and re.search(r"\b\d{1,2}[-/]\d{1,2}[-/]20\d{2}\b", str(point))
    ]
    if reporting_points:
        required.add("reporting date and venue")
    indicators = ("aadhaar", "domicile", "caste certificate", "dob proof",
                  "date of birth", "mark sheet", "marksheet")
    if (re.search(r"\bdocuments?\b", evidence_text)
            and sum(term in evidence_text for term in indicators) >= 3):
        required.add("required documents")

    return {
        facet for facet in required
        if not any(_claim_covers_missing_facet(claim, facet, records_by_id)
                   for claim in claims)
    }


def _claim_covers_missing_facet(claim, facet, records_by_id=None):
    """Check whether a validated statement covers a requested overview facet."""
    text = str(claim.get("text") or "").casefold()
    if facet == "B.Tech course names":
        return all(term in text for term in (
            "computer science", "information technology", "electronics engineering",
            "industrial engineering",
        ))
    if facet == "eligibility with mandatory subjects and marks":
        mandatory = ("physics" in text
                     and ("mathematics" in text or "maths" in text)
                     and re.search(r"\b(?:compulsory|mandatory|required)\b", text))
        third = re.search(r"\b(?:additional|third|one more)\b", text)
        marks = "45" in text and "40" in text
        combination = re.search(
            r"\b(?:specified|combined|selected|these|three)\s+subjects?\b"
            r"|\bsubjects?\s+taken\s+together\b|\bsubject\s+combination\b",
            text,
        )
        return bool(mandatory and third and marks and combination)
    if facet == "application dates":
        if not re.search(r"\b(?:apply|application|applications|submitted|submit)\b", text):
            return False
        if records_by_id:
            record = next(iter(records_by_id.values()))
            dates = (record.get("structured_data") or {}).get("important_dates") or {}
            start_date = str(dates.get("start_date") or "").strip()
            last_date = str(dates.get("last_date") or "").strip()
            return bool(start_date and last_date and start_date in text and last_date in text)
        return bool(re.search(r"\b\d{1,2}[-/]\d{1,2}[-/]20\d{2}\b", text))
    if facet == "reporting date and venue":
        if not re.search(r"\breport(?:ing)?\b", text):
            return False
        if not records_by_id:
            return False
        record = next(iter(records_by_id.values()))
        points = (record.get("structured_data") or {}).get("key_points") or []
        if not isinstance(points, (list, tuple)):
            points = [points]
        for point in points:
            source = str(point).casefold()
            if not re.search(r"\b(?:report(?:ing)?|merit list)\b", source):
                continue
            room = re.search(r"\broom\s*\d+\b", source)
            dates = re.findall(r"\b\d{1,2}[-/]\d{1,2}[-/]20\d{2}\b", source)
            if room and dates and room.group(0) in text and any(d in text for d in dates):
                return True
        return False
    if facet == "required documents":
        indicators = ("aadhaar", "domicile", "caste", "birth", "mark")
        return bool(sum(word in text for word in indicators) >= 3
                    and re.search(r"\bdocuments?|marksheets?|certificates?\b", text))
    return False


def _verified_application_deadline(question, record):
    """Answer a narrow deadline request only when record text links it to applications.

    Important dates can also describe reporting or merit publication. Do not
    interpret last_date as an application deadline without textual corroboration.
    """
    q = str(question or "").casefold()
    deadline_words = re.search(
        r"\b(?:deadline|last\s+date|closing\s+date|due\s+date|end\s+date)\b", q,
    )
    if not deadline_words:
        return None
    if re.search(r"\b(?:reporting|report|verification|merit\s+list|fee\s+payment)\b", q):
        return None  # Other dates must be answered from their own evidence.

    info = record.get("structured_data") or {}
    dates = info.get("important_dates") or {}
    deadline = str(dates.get("last_date") or "").strip()
    if not re.fullmatch(r"\d{2}[-/]\d{2}[-/]20\d{2}|20\d{2}-\d{2}-\d{2}", deadline):
        return None
    date_formats = ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d")
    if not any(_valid_deadline_date(deadline, fmt) for fmt in date_formats):
        return None

    details = [str(info.get("action_required") or "")]
    points = info.get("key_points") or []
    if isinstance(points, list):
        details.extend(str(p) for p in points)
    else:
        details.append(str(points))
    # Require the specific last date in a sentence explicitly about applying.
    if not any(deadline in detail and re.search(
        r"\b(?:apply|applying|applications?|submit|submission)\b",
        detail, re.I,
    ) for detail in details):
        return None

    if re.search(r"\b(?:applications?|apply|applying|submission)\b", q):
        return f"The last date to apply online is {deadline}."
    # Generic 'what is its deadline?' is safe only because the same record
    # explicitly identifies its last_date as an application deadline.
    return f"The application deadline is {deadline}."


def _valid_deadline_date(value, fmt):
    try:
        datetime.strptime(value, fmt)
        return True
    except ValueError:
        return False


def answer_from_records(question, records, active_notice=None, current_state=None):
    """Generate an answer using the supplied notices and recent conversation."""
    st = current_state if current_state is not None else state
    if st is state:
        _sync_state()
    context, evidence, records_by_id = build_evidence_bundle(
        records,
        question,
        build_context_string,
        extract_relevant_snippets,
    )
    # Phase 2 local diagnostics. Enable with UNIAI_DEBUG=1.
    # Never enable verbose evidence logging on a public deployment.
    debug_phase2 = os.getenv("UNIAI_DEBUG", "0").lower() in ("1", "true", "yes")
    if debug_phase2:
        print("\n========== PHASE 2 EVIDENCE BUNDLE ==========", flush=True)
        print("Question:", question, flush=True)
        print("Evidence IDs:", list(records_by_id.keys()), flush=True)
        print("Evidence references:", flush=True)
        for ref_id, fact in evidence.items():
            print(ref_id, "=>", str(fact.get("text", ""))[:200], flush=True)
        print("=============================================", flush=True)

    if not records_by_id:
        st.append_turn(question, NO_RESULTS_MESSAGE, records=[])
        if st is state:
            _sync_back()
        return NO_RESULTS_MESSAGE

    # Phase 4: deterministic, sourced reply for verified application deadlines.
    # This prevents the LLM from adding an academic-session year without citing
    # its title evidence and thereby losing a fact already in structured data.
    if len(records_by_id) == 1:
        record = next(iter(records_by_id.values()))
        deadline_answer = _verified_application_deadline(question, record)
        if deadline_answer is not None:
            rendered, supporting_records = _render_supported_claims(
                [{"text": deadline_answer, "notice_ids": [str(record["notice_id"])]}],
                records_by_id,
            )
            st.append_turn(
                question, rendered, records=supporting_records,
                active_notice=record,
            )
            if st is state:
                _sync_back()
            if debug_phase2:
                print("[UniAI] Verified application-deadline fast path:",
                      record.get("notice_id"), flush=True)
            return rendered

    # Missing exact values require caution: a null structured field is not
    # proof that the original PDF explicitly says 'not specified'. For a
    # single, identified notice and a narrowly requested amount, give a
    # data-grounded response rather than asking Ollama to invent a negative
    # evidence reference. Preserve the notice so FastAPI attaches its PDF.
    amount_question = bool(
        re.search(r"\bapplication[\s-]*fees?\b", question, re.I)
        or (re.search(r"\bguaranteed\b", question, re.I)
            and re.search(r"\b(?:placement|package|salary|ctc)\b", question, re.I))
    )
    if len(records_by_id) == 1 and amount_question:
        record = next(iter(records_by_id.values()))
        missing_answer = missing_amount_guidance(question, record)
        if missing_answer is not None:
            if debug_phase2:
                print("[UniAI] Safe missing-value path; source notice:",
                      record.get("notice_id"), flush=True)
            rendered, supporting_records = _render_supported_claims(
                [{"text": missing_answer, "notice_ids": [str(record["notice_id"])]}],
                records_by_id,
            )
            st.append_turn(
                question, rendered, records=supporting_records,
                active_notice=record,
            )
            if st is state:
                _sync_back()
            return rendered

    recent_context = st.format_recent_history(max_turns=2)

    try:
        response = rag_chain.invoke(
            {
                "context": context,
                "question": question,
                "history": recent_context,
            }
        )
        content = _response_text(response)

        # Validate original citations before attempting any recovery.
        try:
            payload = _parse_claim_payload(content)
        except (ValueError, json.JSONDecodeError, TypeError) as parse_error:
            payload = {"claims": []}
            if debug_phase2:
                print("[UniAI] Initial JSON parse failed:", parse_error, flush=True)

        claims = validate_claims(
            payload.get("claims"), evidence, records_by_id, debug=debug_phase2,
        )
        claims = _apply_eligibility_guard(claims, records_by_id, debug=debug_phase2)

        # A comparison should cite both retrieved notices when both have
        # relevant evidence. Retry ONCE if Ollama merged notice IDs or the
        # validator rejected one/both claims. Never accept the original
        # unvalidated output as a fallback.
        is_comparison_question = bool(re.search(
            r"\b(compare|comparison|differences? between|respective|both notices)\b",
            question, re.I,
        ))
        expected_ids = set(records_by_id)
        validated_ids = {
            notice_id for claim in claims for notice_id in claim["notice_ids"]
        }
        malformed_multinotice = any(
            isinstance(item, dict) and isinstance(item.get("notice_ids"), list)
            and len(item["notice_ids"]) != 1
            for item in (payload.get("claims") or [])
            if isinstance(payload.get("claims"), list)
        )
        needs_comparison_retry = (
            is_comparison_question and len(expected_ids) >= 2
            and (malformed_multinotice or not expected_ids.issubset(validated_ids))
        )

        if needs_comparison_retry and os.getenv("UNIAI_ENABLE_LLM_REPAIRS", "0") == "1":
            repair_question = (
                question + "\n\nCOMPARISON OUTPUT CORRECTION: The previous "
                "response failed evidence validation or omitted a compared "
                "notice. Generate a NEW JSON answer using the provided "
                "retrieved context. Output a separate claim for EACH of the "
                "two relevant notices. Every claim MUST have exactly ONE "
                "notice ID and evidence_refs from that SAME notice. "
                "Do not merge the two notices into one sentence or claim. "
                "Prioritize DOCUMENT VERIFICATION REQUIREMENTS such as "
                "required documents, originals, photocopies and certificates "
                "rather than just reporting schedules. Use only supported "
                "facts, and do not invent missing requirements."
            )
            try:
                retry_response = rag_chain.invoke({
                    "context": context,
                    "question": repair_question,
                    "history": recent_context,
                })
                retry_content = _response_text(retry_response)
                retry_payload = _parse_claim_payload(retry_content)
                retry_claims = validate_claims(
                    retry_payload.get("claims"), evidence, records_by_id,
                    debug=debug_phase2,
                )
                if debug_phase2:
                    print("[UniAI] Comparison retry raw:", repr(retry_content), flush=True)
                    print("[UniAI] Comparison retry accepted:", repr(retry_claims), flush=True)
                # Retain supported claims from either attempt, but favor a
                # complete, validated two-notice comparison on retry.
                retry_ids = {
                    notice_id for claim in retry_claims
                    for notice_id in claim["notice_ids"]
                }
                if expected_ids.issubset(retry_ids):
                    claims = retry_claims
                elif not expected_ids.issubset(validated_ids):
                    claims = retry_claims if len(retry_ids) > len(validated_ids) else claims
            except (ValueError, TypeError, json.JSONDecodeError) as retry_error:
                if debug_phase2:
                    print("[UniAI] Comparison retry failed:", retry_error, flush=True)

        # A single-notice overview may contain correct claims while omitting
        # courses, eligibility, application, reporting, or documents. Retry ONCE,
        # only claims that pass citation validation and the AND/OR safeguard.
        # This is independent of the existing comparison retry above.
        if not is_comparison_question:
            missing_facets = _missing_notice_overview_facets(
                question, records_by_id, evidence, claims,
            )
            if missing_facets and os.getenv("UNIAI_ENABLE_LLM_REPAIRS", "0") == "1":
                if debug_phase2:
                    print("[UniAI] Missing overview facets:", sorted(missing_facets), flush=True)
                repair_question = (
                    question + "\n\nANSWER COMPLETENESS CORRECTION: Your earlier "
                    "response omitted these essential parts: "
                    + ", ".join(sorted(missing_facets)) + ". "
                    "Regenerate ONE valid JSON object with atomic claims and "
                    "exact evidence_refs. Include the complete list of relevant "
                    "B.Tech courses only when supported. For eligibility, do NOT "
                    "write 'Physics, Mathematics, or other subjects' or overall "
                    "aggregate: when the notice requires both Physics AND "
                    "Mathematics, explicitly state BOTH are mandatory, PLUS ONE "
                    "additional subject from the officially permitted list, with "
                    "at least 45% marks (40% for reserved categories) in the "
                    "specified three subjects taken together. Do NOT use the "
                    "unqualified word aggregate. Only state these requirements if supported "
                    "by the evidence. If stating the 2026-2027 academic session, "
                    "cite the evidence containing 2027 (usually the title). "
                    "Use short separate claims for courses and eligibility. "
                    "For supported notice facts, include reporting date, location/room, "
                    "and a specific list of required documents, each as short claims. "
                    "Do not repeat unsupported facts or invent details."
                )
                try:
                    repair_raw = _response_text(rag_chain.invoke({
                        "context": context,
                        "question": repair_question,
                        "history": recent_context,
                    }))
                    repair_payload = _parse_claim_payload(repair_raw)
                    repair_claims = validate_claims(
                        repair_payload.get("claims"), evidence, records_by_id,
                        debug=debug_phase2,
                    )
                    repair_claims = _apply_eligibility_guard(
                        repair_claims, records_by_id, debug=debug_phase2,
                    )
                    # Keep original supported statements, then add every
                    # newly covered facet (including reporting and documents).
                    # The retry claims were validated and eligibility-guarded
                    # above; never merge unvalidated LLM output.
                    seen = {
                        " ".join(str(c.get("text") or "").casefold().split())
                        for c in claims
                    }
                    outstanding = set(missing_facets)
                    for candidate in repair_claims:
                        normalized = " ".join(
                            str(candidate.get("text") or "").casefold().split()
                        )
                        if not normalized or normalized in seen:
                            continue
                        newly_covered = {
                            facet for facet in outstanding
                            if _claim_covers_missing_facet(
                                candidate, facet, records_by_id,
                            )
                        }
                        if not newly_covered:
                            continue  # Avoid duplicate course/application facts.
                        claims.append(candidate)
                        seen.add(normalized)
                        outstanding -= newly_covered
                        if not outstanding:
                            break
                    if debug_phase2:
                        print("[UniAI] Overview retry raw:", repr(repair_raw), flush=True)
                        print("[UniAI] Overview retry accepted:", repr(repair_claims), flush=True)
                        print("[UniAI] Still missing:", sorted(
                            _missing_notice_overview_facets(
                                question, records_by_id, evidence, claims
                            )
                        ), flush=True)
                except (ValueError, TypeError, json.JSONDecodeError) as retry_error:
                    if debug_phase2:
                        print("[UniAI] Overview retry failed:", retry_error, flush=True)

        # Never return an incomplete comparison as though both notices were
        # checked. The user can retry with a narrower question.
        if is_comparison_question and len(expected_ids) == 2:
            final_ids = {
                notice_id for claim in claims for notice_id in claim["notice_ids"]
            }
            if not expected_ids.issubset(final_ids):
                if debug_phase2:
                    print("[UniAI] Incomplete comparison: missing supported notice claims", flush=True)
                claims = []
        if debug_phase2:
            print("\n========== PHASE 2 CLAIM VALIDATION ==========", flush=True)
            print("Evidence IDs:", list(records_by_id.keys()), flush=True)
            print("Raw LLM response:", repr(content), flush=True)
            print("Parsed claims:", repr(payload.get("claims")), flush=True)
            print("Validated claims:", repr(claims), flush=True)
            print("================================================", flush=True)

        if not claims:
            content = NO_RESULTS_MESSAGE
            supporting_records = []
        else:
            content, supporting_records = _render_supported_claims(
                claims,
                records_by_id,
            )
        selected_active_notice = (
            active_notice
            if len(supporting_records) == 1
            and str(active_notice.get("notice_id")) == str(supporting_records[0].get("notice_id"))
            else None
        ) if active_notice else None
        st.append_turn(
            question,
            content,
            records=supporting_records,
            active_notice=selected_active_notice,
        )
        if st is state:
            _sync_back()
        return content
    except (json.JSONDecodeError, ValueError, TypeError) as error:
        print(f"LLM evidence validation failed: {error}")
        st.append_turn(question, NO_RESULTS_MESSAGE, records=[])
        if st is state:
            _sync_back()
        return NO_RESULTS_MESSAGE


def _parse_claim_payload(content):
    """Parse the model's JSON claim payload, allowing surrounding code fences."""
    text = str(content or "").strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.I)
    if fenced:
        text = fenced.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("The answer model did not return a claim payload.")
    payload = json.loads(text[start:end + 1])
    if not isinstance(payload, dict):
        raise ValueError("The answer model returned an invalid claim payload.")
    return payload


def _render_supported_claims(claims, records_by_id):
    """Render validated claims with citations derived from their supporting IDs."""
    lines = []
    supporting_records = []
    seen_ids = set()
    for claim in claims:
        citations = []
        claim_text = claim["text"]
        for notice_id in claim["notice_ids"]:
            record = records_by_id[notice_id]
            if notice_id not in seen_ids:
                seen_ids.add(notice_id)
                supporting_records.append(record)
            data = record.get("structured_data") or {}
            title = data.get("title") or record.get("title") or "Untitled notice"
            issue_date = data.get("issue_date")
            label = title
            if issue_date:
                label += f" (issued {issue_date})"
            url = record.get("url")
            if url:
                label += f" — PDF: {url}"
            # Keep official URLs readable. Notice-PDF attribution is appended
            # separately in the source citation below.
            citations.append(label)
        lines.append(f"{claim_text} [Source: {'; '.join(citations)}]")
    return "\n\n".join(lines), supporting_records


def _handle_casual_chat(question, current_state=None):
    """Produce conversational answers for casual chat, greetings, and identity queries."""
    st = current_state if current_state is not None else state
    text_lower = question.lower().strip()

    # Identity query: "what is my name", "who am i"
    if any(re.search(p, text_lower) for p in [r"\b(?:what(?:\s+is|\s*'s|s)?|tell\s+me)\b.*\bmy\s+name\b", r"\bwho\s+am\s+i\b", r"\bdo\s+you\s+(?:remember|know)\s+my\s+name\b"]):
        user_name = st.get_user_name()
        if user_name:
            return f"Your name is {user_name}."
        return "I don't know your name yet. Feel free to introduce yourself anytime!"

    # Identity declaration / correction
    current_name = st.extract_and_remember_user_name(question)
    if current_name and any(k in text_lower for k in ["my name is", "call me", "correct my name", "correction", "i am"]):
        return f"Got it, {current_name}! How can I assist you with MAKAUT notices today?"

    # Assistant persona: "who are you", "what can you do"
    if any(re.search(p, text_lower) for p in [r"\bwho\s+are\s+you\b", r"\bwhat\s+can\s+you\s+do\b", r"\bhow\s+can\s+you\s+help\b"]):
        return (
            "I am UniAI, an independent academic assistant for MAKAUT notices. "
            "I can help you find and understand university notices, entrance exam schedules "
            "(such as WBJEE and JELET), fees, deadlines, and required documents."
        )

    # Thanks / pleasantry
    if any(k in text_lower for k in ["thank you", "thanks"]):
        return "You're welcome! Let me know if you need any more details from university notices."

    # Greeting
    user_name = st.get_user_name()
    greeting_suffix = f", {user_name}" if user_name else ""
    return f"Hello{greeting_suffix}! I am UniAI, your assistant for MAKAUT university notices. How can I help you today?"


# ---------------------------------------------------------------------------
# Phase 6: deterministic routing, source-preserving follow-ups and safe answers
# ---------------------------------------------------------------------------
# The RAG claim validator above is retained for complex, non-structured queries.
# Straightforward searches and metadata questions do not require an LLM call.


def _record_source(record):
    url = str(record.get("url") or "").strip()
    return f"Official source: {url}" if url else "Official source PDF URL is unavailable in this record."


def _record_heading(record):
    sd = record.get("structured_data") or {}
    return str(sd.get("title") or record.get("title") or "Untitled notice")


def _plain(value):
    if isinstance(value, dict):
        return "; ".join(f"{k.replace('_', ' ')}: {_plain(v)}" for k, v in value.items()
                         if v is not None and _plain(v))
    if isinstance(value, (tuple, list)):
        return "; ".join(str(v).strip() for v in value if v is not None and str(v).strip())
    return str(value or "").strip()


def _save_reply(st, question, answer, records=None, *, active=None, preserve=False):
    st.append_turn(question, answer, records=records, active_notice=active,
                   preserve_notice_list=preserve)
    return answer


def _structured_notice_overview(record, *, max_points=9):
    """Expanded factual notice summary; never invent missing OCR fields."""
    sd = record.get("structured_data") or {}
    lines = [_record_heading(record)]
    if sd.get("issue_date"):
        lines.append(f"Issued: {_plain(sd['issue_date'])}")
    if sd.get("reference_no"):
        lines.append(f"Reference: {_plain(sd['reference_no'])}")
    if sd.get("target_audience"):
        lines.append(f"Who it concerns: {_plain(sd['target_audience'])}")
    if sd.get("summary"):
        lines.append(f"Overview: {_plain(sd['summary'])}")
    if sd.get("action_required"):
        lines.append(f"Action required: {_plain(sd['action_required'])}")
    dates = sd.get("important_dates") or {}
    if isinstance(dates, dict):
        if dates.get("start_date"):
            lines.append(f"Start date (as extracted): {_plain(dates['start_date'])}")
        if dates.get("last_date"):
            lines.append(f"Last date (as extracted): {_plain(dates['last_date'])}")
    points = sd.get("key_points") or []
    if not isinstance(points, (list, tuple)):
        points = [points]
    unique = []
    for point in points:
        if not point:
            continue
        candidate = str(point).strip()
        # Unsafe OCR paraphrases can invert mandatory-subject requirements.
        # Do not publish an ambiguous eligibility claim as a verified rule.
        if re.search(r"\bPhysics\s*,\s*Mathematics\s*,\s*or\b", candidate, re.I) or (
            re.search(r"\beligibilit", candidate, re.I) and
            re.search(r"\b(?:45|40)\s*%\s+aggregate\b", candidate, re.I)
        ):
            candidate = ("Eligibility extraction is ambiguous. Verify mandatory "
                         "subjects and the marks calculation in the official PDF.")
        if candidate not in unique:
            unique.append(candidate)
    if unique:
        lines.append("Important details:")
        lines.extend(f"- {point[:650]}" for point in unique[:max_points])
    lines.append(_record_source(record))
    return "\n".join(lines)


def _field_answer(question, record, field=None):
    """Answer high-confidence field questions without risky unvalidated LLM text.

    Return None only when the question is complex and needs an evidence-grounded
    RAG answer. Otherwise return an explicit answer/source even when a field is
    absent from extracted structured data.
    """
    sd = record.get("structured_data") or {}
    lower = str(question or "").casefold()
    source = _record_source(record)
    title = _record_heading(record)
    # A request for reopening is NOT a request to list more hostel notices.
    # Closure-end dates do not establish an official reopening date by themselves.
    if re.search(r"\breopen(?:s|ed|ing)?\b", lower):
        candidates = [sd.get("action_required"), *(sd.get("key_points") or []),
                      sd.get("summary")]
        for statement in candidates:
            value = _plain(statement)
            if re.search(r"\breopen(?:s|ed|ing)?\b", value, re.I) and re.search(
                r"\b(?:\d{1,2}[-/]\d{1,2}[-/]20\d{2}|\d{1,2}\s+[A-Za-z]+\s+20\d{2})\b", value
            ):
                return f"According to '{title}': {value}\n{source}"
        return (f"I cannot confirm an explicit reopening date from the extracted "
                f"details of '{title}'. Closure dates do not automatically "
                f"establish a reopening date. Please check the original PDF.\n{source}")
    if field == "source" or re.search(r"\b(?:official\s+(?:pdf\s+)?(?:source|link)|pdf\s+(?:source|link)|source\s+url)\b", lower):
        return f"Source for '{title}':\n{source}"
    if field == "reference_number":
        value = sd.get("reference_no")
        return (f"Reference number: {_plain(value)}\n{source}" if value
                else f"The extracted notice has no verified reference number.\n{source}")
    if field == "issue_date":
        value = sd.get("issue_date")
        return (f"Issue date: {_plain(value)}\n{source}" if value
                else f"The issue date is not available in the extracted record.\n{source}")
    if field == "deadline" or re.search(r"\b(?:deadline|last\s+date|due\s+date)\b", lower):
        verified = _verified_application_deadline(question, record)
        if verified:
            return f"{verified}\n{source}"
        dates = sd.get("important_dates") or {}
        date_value = dates.get("last_date") if isinstance(dates, dict) else None
        if date_value:
            return (f"The extracted notice lists a last date of {_plain(date_value)}. "
                    f"Check the PDF to confirm which action it applies to.\n{source}")
        return f"I could not verify a deadline from this notice's extracted details.\n{source}"
    if field == "fees" or re.search(r"\b(?:application\s+fee|fees?|charges?)\b", lower):
        fees = sd.get("fees") or {}
        amount = fees.get("amount") if isinstance(fees, dict) else None
        currency = fees.get("currency") if isinstance(fees, dict) else None
        application_specific = "application" in lower
        if application_specific:
            # The schema's generic fees.amount is not necessarily an application
            # fee. Extract an explicitly labeled amount from the official OCR
            # or structured text; never convert an admission fee into one.
            texts = [str(sd.get("action_required") or "")]
            texts.extend(str(item) for item in (sd.get("key_points") or []))
            texts.append(str(record.get("raw_text") or "")[:20000])
            money = r"(?:₹|Rs\.?|INR)\s*[\d,]+(?:\.\d+)?|[\d,]+(?:\.\d+)?\s*(?:rupees|INR)"
            for evidence_line in texts:
                match = re.search(
                    rf"\bapplication\s+fees?\b.{{0,90}}?(?:{money})|"
                    rf"(?:{money}).{{0,70}}?\bapplication\s+fees?\b",
                    evidence_line, re.I | re.S,
                )
                if match:
                    fragment = " ".join(match.group(0).split())
                    return f"The official notice states: {fragment}.\n{source}"
            return ("I cannot confirm an application-fee amount from the available "
                    f"extracted details of '{title}'. Consult the official PDF.\n{source}")
        if amount not in (None, "", "null", "None"):
            return f"Fee listed in this notice: {_plain(amount)} {_plain(currency)}.\n{source}"
        return f"I cannot verify a fee amount from the extracted notice details.\n{source}"
    if field in ("documents", "eligibility", "procedure", "location", "time", "contact"):
        expressions = {
            "documents": r"\b(?:documents?|certificate|photocopies?|originals?|aadhaar|marksheets?|proof|verification)\b",
            "eligibility": r"\b(?:eligible|eligibility|qualification|compulsory|mandatory|subjects?|percentage|marks|criteria|12th|10\+2)\b",
            "procedure": r"\b(?:apply|application|registration|submit|submission|portal|steps?|report(?:ing)?|procedure|process)\b",
            "location": r"\b(?:campus|building|venue|room|location|reporting\s+(?:at|venue)|salt\s+lake|haringhata)\b",
            "time": r"\b(?:reopen|leave|closing|closure|time|timing|schedule|hours?|a\.m\.|p\.m\.|date)\b",
            "contact": r"\b(?:contact|phone|mobile|email|helpline|office)\b",
        }
        pat = re.compile(expressions[field], re.I)
        relevant = []
        for entry in [sd.get("action_required"), *(sd.get("key_points") or [])]:
            value = _plain(entry)
            if value and pat.search(value) and value not in relevant:
                relevant.append(value)
        # For documentary questions use high-signal OCR excerpts only when
        # the structured fields have no matching details.
        if not relevant:
            excerpts = extract_relevant_snippets(
                record.get("raw_text") or "", question, max_snippets=2,
                max_chars=450,
            )
            relevant = [e for e in excerpts if pat.search(e)]
        if relevant:
            return f"From '{title}':\n" + "\n".join(
                f"- {item[:700]}" for item in relevant[:7]
            ) + f"\n{source}"
        return (f"I couldn't verify the requested {field} information from the "
                f"available extracted details of '{title}'. Check the original PDF.\n{source}")
    if field in ("details", "summary") or re.search(
        r"\b(?:explain|summari[sz]e|details?|overview|describe|tell me more)\b", lower
    ):
        return _structured_notice_overview(record)
    return None


def _out_of_scope(question):
    lower = str(question or "").casefold()
    # Explicit non-university subjects should not be routed to random PDF data.
    return bool(re.search(
        r"\b(?:cricket|football|world\s+cup|ipl|movie|film|celebrity|weather|stock\s+market|bitcoin)\b",
        lower,
    ) and not re.search(r"\b(?:notice|university|makaut|campus|college)\b", lower))


def _is_list_request(question):
    lower = str(question or "").lower()
    return bool(re.search(
        r"\b(?:find|show|list|give|provide|any|are\s+there|what\s+notices|which\s+notices|recent\s+notices|latest\s+notices)\b",
        lower,
    )) and not bool(re.search(r"\b(?:what\s+is\s+the\s+(?:deadline|fee)|how\s+much)\b", lower))


def _is_single_target(question, parsed):
    lower = str(question or "").lower()
    if getattr(parsed, "count", None) == 1:
        return True
    if re.search(r"\b(?:notices|notifications|list|all|several|multiple)\b", lower):
        return False
    return bool(re.search(r"\b(?:the|a|one|single)\s+(?:[\w-]+\s+){0,12}?(?:notice|notification)\b", lower))


def _no_matches(question):
    return ("I couldn't find a processed MAKAUT notice matching those exact "
            "topic/date/year conditions in the current database. "
            "I won't substitute an unrelated notice. Please try a broader query "
            "or check the official MAKAUT notice board.")


def _safe_grounded_answer(question, records, st, *, preserve=False):
    """Use existing LLM+evidence checks; recover gracefully from provider failures."""
    import logging
    if not records:
        return _save_reply(st, question, _no_matches(question), records=[])
    original_list = list(st.get_last_notice_records()) if preserve else []
    try:
        answer = answer_from_records(
            question, records, active_notice=records[0] if len(records) == 1 else None,
            current_state=st,
        )
        if answer == NO_RESULTS_MESSAGE:
            answer = (_structured_notice_overview(records[0]) if len(records) == 1 else
                      format_notice_list(records))
            _save_reply(st, question, answer, records=records,
                        active=records[0] if len(records) == 1 else None,
                        preserve=preserve)
    except Exception:
        logging.exception("[UniAI] Grounded answer model failed; using extracted notice facts")
        answer = (_structured_notice_overview(records[0]) if len(records) == 1 else
                  format_notice_list(records))
        _save_reply(st, question, answer, records=records,
                    active=records[0] if len(records) == 1 else None,
                    preserve=preserve)
    if preserve and original_list:
        st.set_last_results(original_list)
    return answer


def _comparison_notice_answer(question, st):
    """Compare distinct years without allowing the first year to filter both."""
    from retrieve import retrieve_filtered_notices
    years = list(dict.fromkeys(int(y) for y in re.findall(r"\b(20\d{2})\b", question)))
    if len(years) < 2:
        return None
    found = []
    missing = []
    for year in years[:3]:
        candidates = retrieve_filtered_notices(question, top_k=1,
                                               force_year=year)
        if candidates:
            found.append((year, candidates[0]))
        else:
            missing.append(year)
    lines = []
    for year, record in found:
        sd = record.get("structured_data") or {}
        details = [str(p) for p in sd.get("key_points") or [] if re.search(
            r"\b(?:documents?|originals?|photocopies?|certificates?|verification|admission)\b", str(p), re.I
        )]
        if not details:
            details = [str(sd.get("summary") or "No matching details extracted")]
        lines.append(f"{year} — {_record_heading(record)}")
        lines.extend(f"- {point[:700]}" for point in details[:5])
        lines.append(_record_source(record))
    if missing:
        lines.append("I couldn't find a matching processed notice for: " +
                     ", ".join(map(str, missing)) + ". No comparison facts were invented.")
    if not lines:
        lines = [_no_matches(question)]
    records = [record for _, record in found]
    return _save_reply(st, question, "\n\n".join(lines), records=records,
                       active=None, preserve=False)


def ask_uniai(question, state=None):
    """Reliable entry point for notice search, follow-ups, and grounded Q&A."""
    from retrieve import (retrieve_filtered_notices, detect_search_topics,
                          _requested_issue_date_any_position)
    from Module4.query_understanding import fallback_understand_query
    import logging

    question = str(question or "").strip()
    if not question:
        return "Please enter a question."
    st = state if state is not None else globals()["state"]
    if _out_of_scope(question):
        return _save_reply(st, question, "I only answer questions about MAKAUT university notices. "
                           "Please ask about admissions, exams, hostels, registration or other notices.")

    # Avoid a Groq classification API call for deterministic student queries.
    # Opt-in classifier remains available for experiments without breaking
    # production if Groq is rate-limited or unavailable.
    if os.getenv("UNIAI_USE_LLM_CLASSIFIER", "0") == "1":
        try:
            parsed = understand_query(question, st)
        except Exception:
            logging.exception("[UniAI] Classifier failed; using deterministic parser")
            parsed = fallback_understand_query(question, st)
    else:
        parsed = fallback_understand_query(question, st)

    if parsed.intent == "casual_chat":
        # 'My name is Example Student.' is an explicit name statement despite
        # the generic word 'student'. Don't infer a name from any other phrase.
        name_match = re.search(
            r"\b(?:my\s+name\s+is|call\s+me|correct\s+my\s+name\s+to)\s+"
            r"([A-Za-z]+(?:\s+[A-Za-z]+)?)\b", question, re.I,
        )
        if name_match:
            full_name = name_match.group(1).strip().title()
            st.session_memory["user_name"] = full_name
            reply = f"Got it, {full_name}! How can I help with MAKAUT notices?"
        else:
            reply = _handle_casual_chat(question, current_state=st)
        return _save_reply(st, question, reply)

    if parsed.intent == "ordinal_followup":
        original_list = st.get_last_notice_records()
        ordinal = parsed.ordinal
        if ordinal == -1:
            ordinal = len(original_list)
        if not original_list:
            return _save_reply(st, question,
                               "Please ask me to list notices first, then choose an item number.")
        if not ordinal or not 1 <= ordinal <= len(original_list):
            return _save_reply(st, question,
                               f"The original list contains {len(original_list)} notices. "
                               f"Please choose 1–{len(original_list)}.")
        selected = original_list[ordinal - 1]
        if re.search(r"\b(?:explain|details?|summary|summari[sz]e|describe)\b", question, re.I):
            answer = _structured_notice_overview(selected)
        else:
            answer = format_notice_line(selected)
        return _save_reply(st, question, answer, records=[selected], active=selected,
                           preserve=True)

    # A named NEW topic or year always overrides a previous active notice.
    active = st.get_active_notice()
    changed = explicitly_changes_notice_topic(question, active)
    named_topics = detect_search_topics(question)
    explicit_year = re.search(r"\b(20\d{2})\b", question)
    is_new_search = bool(re.search(r"\b(?:find|search|list)\b", question, re.I)) or (
        bool(re.search(r"\b(?:show|give|are\s+there)\b", question, re.I))
        and bool(named_topics or explicit_year or re.search(
            r"\b(?:notices?|notifications?|latest|recent|new)\b", question, re.I))
    )
    # 'Give me its source' and 'show this notice's deadline' reuse the active
    # record even though their sentences start with a command verb.
    if active and not changed and not explicit_year and re.search(
        r"\b(?:its|this\s+notice|that\s+notice|about\s+it|there)\b",
        question, re.I,
    ):
        is_new_search = False
    # A single active notice owns field questions, even when its topic is
    # mentioned explicitly (e.g. "When will the hostel reopen?").
    # Global latest/today/yesterday requests remain fresh searches.
    global_temporal = parsed.intent in ("latest_notices", "today_notices", "yesterday_notices")
    if active is not None and not changed and not is_new_search and not global_temporal and (
        parsed.intent == "notice_followup" or parsed.use_active_notice or
        parsed.requested_field is not None or
        re.search(r"\b(?:this\s+notice|that\s+notice|its|there|it)\b", question, re.I)
    ):
        result = _field_answer(question, active, parsed.requested_field)
        if result is not None:
            return _save_reply(st, question, result, records=[active], active=active,
                               preserve=True)
        return _safe_grounded_answer(question, [active], st, preserve=True)

    # Do not start a new database search for generic facts about one of several
    # previously displayed notices. Require disambiguation instead.
    if (active is None and len(st.get_last_notice_records()) > 1
            and not is_new_search and not named_topics and not explicit_year
            and (parsed.requested_field is not None or re.search(
                r"\b(?:what|when|where|who|how|explain|its|this|that|there)\b",
                question, re.I,
            ))):
        return _save_reply(st, question, "Which notice do you mean? "
                           f"Choose a number from 1 to {len(st.get_last_notice_records())}.")

    # An under-specified question after a multi-notice list requires selection.
    if not is_new_search and parsed.intent == "notice_followup" and not active:
        if len(st.get_last_notice_records()) > 1:
            return _save_reply(st, question, "Which notice do you mean? "
                               f"Choose a number from 1 to {len(st.get_last_notice_records())}.")

    if parsed.intent == "multi_notice_followup":
        earlier = st.get_last_answer_records()
        if len(earlier) >= 2:
            return _safe_grounded_answer(question, earlier, st, preserve=True)
        return _save_reply(st, question, "Please choose two notices to compare first.")

    if re.search(r"\b(?:compare|comparison|difference\s+between)\b", question, re.I):
        try:
            compared = _comparison_notice_answer(question, st)
            if compared is not None:
                return compared
        except Exception:
            logging.exception("[UniAI] Comparison retrieval failed")
            return _save_reply(st, question, "Notice comparison is temporarily unavailable. Please retry.")

    # Chronological global requests do not hit Pinecone or Groq.
    is_pure_latest = parsed.intent in ("latest_notices", "today_notices", "yesterday_notices") and not named_topics
    issue_date = _requested_issue_date_any_position(question)
    topic_specific = bool(named_topics)
    try:
        requested = getattr(parsed, "count", None) or extract_requested_count(question)
        count = min(10, max(1, int(requested or (1 if _is_single_target(question, parsed) else 5))))
        if is_pure_latest:
            from retrieve import retrieve_time_based
            if parsed.intent == "today_notices":
                records = retrieve_time_based("notices published today", top_k=count)
            elif parsed.intent == "yesterday_notices":
                records = retrieve_time_based("notices published yesterday", top_k=count)
            else:
                records = retrieve_time_based("latest university notices", top_k=count)
        elif topic_specific or issue_date is not None or explicit_year:
            records = retrieve_filtered_notices(question, top_k=count,
                                                 sort_latest=bool(re.search(
                                                     r"\b(?:latest|recent|most\s+recent)\b", question, re.I)))
        else:
            records = retrieve_context(question, top_k=count)
    except Exception:
        logging.exception("[UniAI] Retrieval error")
        return _save_reply(st, question,
                           "I couldn't access the notice database right now. "
                           "Please retry in a moment; this is not a confirmed no-results answer.")

    if not records:
        if parsed.intent == "today_notices":
            reply = "No processed notices with today's official issue date are currently available in the database."
        elif parsed.intent == "yesterday_notices":
            reply = "No processed notices with yesterday's official issue date are currently available in the database."
        else:
            reply = _no_matches(question)
        return _save_reply(st, question, reply, records=[])

    if _is_list_request(question) or is_pure_latest or issue_date is not None:
        content = (format_notice_list(records) if len(records) > 1
                   else format_notice_line(records[0]))
        return _save_reply(st, question, content, records=records,
                           active=records[0] if len(records) == 1 else None)

    # Single-document specific questions use precise field extraction first.
    if len(records) == 1:
        field_answer = _field_answer(question, records[0], parsed.requested_field)
        if field_answer is not None:
            return _save_reply(st, question, field_answer, records=records,
                               active=records[0])
    return _safe_grounded_answer(question, records, st)

if __name__ == "__main__":
    print("\n🎓 UniAI — University AI Assistant")
    print("Type 'exit' to stop.\n")

    while True:
        question = input("You: ").strip()
        if question.lower() in ("exit", "quit"):
            print("UniAI: Goodbye! 👋")
            break
        if not question:
            continue

        answer = ask_uniai(question)
        print(f"\nUniAI: {answer}\n")
