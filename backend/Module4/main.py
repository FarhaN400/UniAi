
import os
import sys
import re
import json
from datetime import datetime, date

from langchain_ollama import ChatOllama

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


MODEL_NAME = "qwen3:4b-instruct"
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
    data = record.get("structured_data", {})
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



model = ChatOllama(
    model=MODEL_NAME,
    temperature=0,
    num_ctx=8192,
    num_predict=1024,
    keep_alive=os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
)

rag_chain = rag_prompt | model

state = ConversationState()
chat_history = state.chat_history
last_notice_records = state.last_notice_records
last_latest_question = None


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

        if needs_comparison_retry:
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
            if missing_facets:
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
            "I am UniAI, the official University AI Assistant for MAKAUT. "
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


def ask_uniai(question, state=None):
    """Ask a university notice question and return the final answer."""
    global last_latest_question, last_notice_records, chat_history

    if not question or not str(question).strip():
        return "Please enter a question."

    st = state if state is not None else globals()["state"]
    if st is globals()["state"]:
        _sync_state()

    # Fast path: Follow-up requesting single notice or detail when active notice exists
    if is_single_notice_follow_up(question) and (st.get_active_notice() or st.get_last_notice_records()):
        active = st.get_active_notice() or st.get_last_notice_records()[0]
        content = format_notice_line(active)
        st.append_turn(question, content, records=[active], active_notice=active)
        if st is globals()["state"]:
            _sync_back()
        return content

    if (is_notice_detail_follow_up(question)
            and (st.get_active_notice() or st.get_last_notice_records())
            and not explicitly_changes_notice_topic(
                question, st.get_active_notice() or st.get_last_notice_records()[0])):
        active = st.get_active_notice() or st.get_last_notice_records()[0]
        return answer_from_records(question, [active], active_notice=active, current_state=st)

    # Query Understanding Layer
    parsed = understand_query(question, st)

    # Multi-document follow-ups must reuse EXACTLY the documents referenced
    # by the previous answer, not the Pinecone candidate pool.
    if parsed.intent == "multi_notice_followup":
        prior = st.get_last_answer_records()
        if os.getenv("UNIAI_DEBUG", "0") == "1":
            print("[UniAI] multi-notice follow-up; reused notice IDs:",
                  [r.get("notice_id") for r in prior])
        if len(prior) >= 2:
            return answer_from_records(question, prior, current_state=st)
        return "I need the two notices to compare. Please ask me to show them first."

    # 1. Casual Chat
    if parsed.intent == "casual_chat":
        content = _handle_casual_chat(question, current_state=st)
        st.append_turn(question, content)
        if st is globals()["state"]:
            _sync_back()
        return content

    # 2. Ordinal Follow-up ("now the 5th one", "show the second one")
    if parsed.intent == "ordinal_followup":
        ordinal = parsed.ordinal or extract_notice_ordinal(question) or 1
        last_records = st.get_last_notice_records()

        if last_records and len(last_records) >= ordinal:
            selected_record = last_records[ordinal - 1]
        else:
            source_question = last_latest_question or "latest notices"
            try:
                records = retrieve_context(source_question, top_k=ordinal)
            except Exception as error:
                print(f"Retrieval failed: {error}")
                return NO_RESULTS_MESSAGE

            if len(records) < ordinal:
                return (
                    f"I found only {len(records)} latest notices, "
                    f"so notice {ordinal} is not available."
                )
            selected_record = records[ordinal - 1]

        content = format_notice_line(selected_record)
        st.append_turn(question, content, records=[selected_record], active_notice=selected_record)
        if st is globals()["state"]:
            _sync_back()
        return content

    # 3. Active Notice Follow-up. A new explicit year/topic must trigger fresh search.
    active_record = st.get_active_notice()
    active_text = ""
    if active_record:
        active_text = str(active_record.get("title", "")) + " " + str(active_record.get("structured_data", {}))
    explicit_year = re.search(r"\b(20\d{2})\b", question)
    conflicting_year = bool(explicit_year and active_record and explicit_year.group(1) not in active_text)
    explicit_topic = extract_supported_topic(question)
    conflicting_topic = bool(explicit_topic and active_record and explicit_topic not in active_text.lower())
    # Detect explicitly named new subjects (e.g. CET registration after hostel).
    topic_switch = explicitly_changes_notice_topic(question, active_record)
    # Also guard when only last results exist (no active notice explicitly set).
    if not active_record and st.get_last_notice_records():
        topic_switch = explicitly_changes_notice_topic(
            question, st.get_last_notice_records()[0]
        )
    conflicting_topic = conflicting_topic or topic_switch
    # Diagnostics for follow-up selection. Enable with UNIAI_DEBUG=1.
    if os.getenv("UNIAI_DEBUG", "0").lower() in ("1", "true", "yes"):
        print("\n[DEBUG FOLLOW-UP]")
        print("Question:", question)
        print("Parsed intent:", parsed.intent)
        print("Use active notice:", parsed.use_active_notice)
        print("Conflicting year:", conflicting_year)
        print("Conflicting topic:", conflicting_topic)
        print("Active notice ID:", st.get_active_notice_id())
        print("Last notice count:", len(st.get_last_notice_records()))

    if (parsed.intent == "notice_followup" or parsed.use_active_notice) and not (conflicting_year or conflicting_topic):
        active = st.get_active_notice() or (st.get_last_notice_records() or [None])[0]
        if active:
            if os.getenv("UNIAI_DEBUG", "0").lower() in ("1", "true", "yes"):
                print("Follow-up route: active notice")
                print("Selected notice ID:", active.get("notice_id"))
                print("Selected notice title:", active.get("title"))
                print("Structured data:", active.get("structured_data"))
                print("Source URL:", active.get("url"))
            return answer_from_records(question, [active], active_notice=active, current_state=st)
    elif os.getenv("UNIAI_DEBUG", "0").lower() in ("1", "true", "yes"):
        print("Follow-up route: skipped; proceeding to fresh retrieval")

    # 4. Topic Search
    topic = parsed.topic or extract_supported_topic(question)
    if topic:
        is_latest_topic = (is_latest_topic_notice_query(question)
                           or (parsed.temporal_scope in ("latest", "recent")
                               and parsed.intent == "topic_search"))
        if is_latest_topic:
            try:
                records = retrieve_topic_notices(topic, top_k=1)
            except Exception as error:
                print(f"Retrieval failed: {error}")
                return NO_RESULTS_MESSAGE

            if not records:
                return NO_RESULTS_MESSAGE

            content = format_notice_line(records[0])
            st.append_turn(question, content, records=records, active_notice=records[0])
            if st is globals()["state"]:
                _sync_back()
            return content

    # 5. Time-based Queries (latest, today, yesterday)
    is_latest_query = parsed.intent in ("latest_notices", "today_notices", "yesterday_notices") or is_latest_notice_query(question)
    is_comparison = bool(re.search(r"\b(compare|comparison|differences? between|respective|both notices)\b", question, re.I))
    requested_top_k = (max(5, parsed.count or 0) if is_comparison else
                       (parsed.count or extract_requested_count(question) or (1 if is_latest_query else 5)))

    # Parsed standalone queries are useful for contextual follow-ups; for fresh searches,
    # retain explicit years and wording from the original student question.
    search_query = question
    if parsed.intent in ("today_notices", "yesterday_notices", "latest_notices"):
        search_query = parsed.standalone_query or question
    if os.getenv("UNIAI_DEBUG", "0") == "1":
        print(f"[UniAI] intent={parsed.intent}, year={parsed.year}, "
              f"topic={parsed.topic}, count={parsed.count}, search={search_query!r}")

    try:
        # Semantic queries retrieve a larger candidate pool before reranking;
        # only up to five evidence records are sent to the answer model.
        retrieval_k = requested_top_k if is_latest_query else max(10, requested_top_k)
        records = retrieve_context(search_query, top_k=retrieval_k)
        # Filter BEFORE trimming the candidate set to the LLM context size.
        # Exact issue-date notice queries must not mix similar older notices.
        if not is_latest_query and not is_comparison:
            records, explicit_date, ambiguous = select_notice_evidence(
                search_query, records, comparison=False
            )
            if ambiguous:
                return (
                    "I found multiple notices on that date matching the topic. "
                    "Please specify the notice title or reference number."
                )
        if not is_latest_query:
            records = filter_explicit_notice_scope(search_query, records)
        if not is_latest_query:
            records = records[:5]
    except Exception as error:
        print(f"Retrieval failed: {error}")
        return NO_RESULTS_MESSAGE

    if not records:
        return NO_RESULTS_MESSAGE

    if is_latest_query:
        last_latest_question = question
        if requested_top_k == 1 or len(records) == 1:
            content = format_notice_line(records[0])
            st.append_turn(question, content, records=records, active_notice=records[0])
            if st is globals()["state"]:
                _sync_back()
            return content

        content = format_notice_list(records)
        st.append_turn(question, content, records=records, active_notice=None)
        if st is globals()["state"]:
            _sync_back()
        return content

    active = records[0] if len(records) == 1 else None
    return answer_from_records(question, records, active_notice=active, current_state=st)


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
