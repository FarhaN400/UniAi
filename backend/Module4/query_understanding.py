import os
import re
import json
from typing import Optional, Literal
from pydantic import BaseModel, Field

from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage, HumanMessage


class QueryUnderstandingResult(BaseModel):
    intent: Literal[
        "casual_chat",
        "latest_notices",
        "today_notices",
        "yesterday_notices",
        "notice_search",
        "topic_search",
        "notice_followup",
        "ordinal_followup",
        "multi_notice_followup",
    ]
    standalone_query: str
    needs_retrieval: bool = True
    use_active_notice: bool = False
    temporal_scope: Optional[Literal["latest", "recent", "today", "yesterday"]] = None
    count: Optional[int] = None
    ordinal: Optional[int] = None
    year: Optional[int] = None
    topic: Optional[str] = None
    requested_field: Optional[str] = None


SYSTEM_PROMPT = """You are the Query Understanding Layer for UniAI, the official University AI Assistant for MAKAUT.
Your job is ONLY to analyze the student's message in the context of recent conversation state and output valid JSON.
DO NOT answer the student's question.
DO NOT invent any dates, notice names, fees, deadlines, eligibility criteria, procedures, years, or university facts.

JSON SCHEMA:
{
  "intent": "casual_chat" | "latest_notices" | "today_notices" | "yesterday_notices" | "notice_search" | "topic_search" | "notice_followup" | "ordinal_followup" | "multi_notice_followup",
  "standalone_query": "<clear standalone query or conversational text>",
  "needs_retrieval": true | false,
  "use_active_notice": true | false,
  "temporal_scope": "latest" | "recent" | "today" | "yesterday" | null,
  "count": <integer or null>,
  "ordinal": <integer or null>,
  "year": <integer or null>,
  "topic": <string or null>,
  "requested_field": "source" | "deadline" | "issue_date" | "reference_number" | "documents" | "eligibility" | "location" | "time" | "summary" | "details" | "fees" | "contact" | "procedure" | null
}

RULES:
1. "casual_chat":
   - Greetings ("Hello", "Hi", "Good morning"), pleasantries ("Thanks", "Thank you", "Understood").
   - Assistant persona ("Who are you?", "What can you do?").
   - Student identity statements or corrections:
     "Hello UniAI, my name is Farha." -> intent: "casual_chat", needs_retrieval: false
     "Actually, correct it. My name is Farhan." -> intent: "casual_chat", needs_retrieval: false
     "Correct my name to Farhan." -> intent: "casual_chat", needs_retrieval: false
     "Actually, my name is Farhan." -> intent: "casual_chat", needs_retrieval: false
     "Can you correct what I said?" -> intent: "casual_chat", needs_retrieval: false
     "What is my name?" / "Who am I?" -> intent: "casual_chat", needs_retrieval: false
   - Casual temporal statements:
     "Today I want to understand what you can do." -> intent: "casual_chat", needs_retrieval: false, temporal_scope: null
     "I recently started using UniAI." -> intent: "casual_chat", needs_retrieval: false, temporal_scope: null
   CRITICAL: Do NOT classify conversational name corrections as notice searches! The word "correct" in conversation does NOT refer to university certificate correction notices.

2. "ordinal_followup":
   - References selecting a notice from a previous list:
     "tell me about the second one" -> intent: "ordinal_followup", ordinal: 2, needs_retrieval: false
     "show the 3rd notice" -> intent: "ordinal_followup", ordinal: 3, needs_retrieval: false
     "now the 5th" -> intent: "ordinal_followup", ordinal: 5, needs_retrieval: false
     "explain the last one" -> intent: "ordinal_followup", ordinal: -1, needs_retrieval: false

3. "notice_followup":
   - Follow-up on the currently active notice when active_notice is present in conversation state:
     "in details", "tell me more", "explain it in detail", "what does this mean?"
     "what is its deadline?" -> requested_field: "deadline"
     "what documents are required?" / "what documents do I need to bring?" -> requested_field: "documents"
     "who is eligible?" -> requested_field: "eligibility"
     "where do I have to go?" -> requested_field: "location"
     "what is the reference number?" -> requested_field: "reference_number"
     "can you give me the official source for this notice?" -> requested_field: "source"
     "what is the application fee mentioned in this WBJEE notice?" -> requested_field: "fees"
     "when do students have to leave?" -> requested_field: "time"
     "when will the hostel reopen?" -> requested_field: "time"
     -> intent: "notice_followup", use_active_notice: true, needs_retrieval: false
   - CRITICAL: When active_notice exists, DO NOT perform a new vector search for contextual follow-up questions!

4. EXPLICIT NEW TOPIC OVERRIDE:
   - If the user query introduces an explicit new topic or different year from the active notice:
     Example: active notice is "Hostel Closure", user says "What documents are required for WBJEE 2026 admission?"
     -> This is an explicit new topic! intent: "topic_search" or "notice_search", needs_retrieval: true, use_active_notice: false, topic: "wbjee", year: 2026.
     Example: active notice is "Registration 2026", user says "Find notices about hostel closure during Durga Puja."
     -> intent: "topic_search", needs_retrieval: true, use_active_notice: false, topic: "hostel closure".

5. "today_notices":
   - Explicitly asking for notices published today:
     "What university notices came today?", "Give me today's notices"
     -> intent: "today_notices", temporal_scope: "today", needs_retrieval: true

6. "yesterday_notices":
   - Explicitly asking for notices published yesterday:
     "What university notices came yesterday?"
     -> intent: "yesterday_notices", temporal_scope: "yesterday", needs_retrieval: true

7. "latest_notices":
   - "What is the most recent university notice?" -> intent: "latest_notices", count: 1, temporal_scope: "latest", needs_retrieval: true
   - "Give me 5 latest university notices." -> intent: "latest_notices", count: 5, temporal_scope: "latest", needs_retrieval: true
   - "Show recent notices" -> intent: "latest_notices", count: 3, temporal_scope: "recent", needs_retrieval: true

8. "topic_search" & "notice_search":
   - Informational questions about MAKAUT notices needing fresh retrieval.
   - Extract topic and year where available.
   - CRITICAL FOR COUNT: A 4-digit year (such as 2024, 2025, 2026) is NEVER a notice count! If the query asks about a singular notice ("notice", "what is the wbjee 2026 notice", "tell me about wbjee 2026 notice"), count MUST be 1. Only set count > 1 when the user explicitly requests multiple notices (e.g., "5 notices").

Return ONLY the raw JSON object. Do not include markdown commentary.
"""


# --------------------------------------------------
# LLM Initialization
# --------------------------------------------------

_understanding_chat = None

def get_understanding_model():
    """Lazily initialize the understanding model."""
    global _understanding_chat
    if _understanding_chat is None:
        try:
            _understanding_chat = ChatOllama(
                model="qwen3:4b-instruct",
                temperature=0,
                num_ctx=8192,
                num_predict=256,
                keep_alive=os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
            )
        except Exception as e:
            print(f"[QueryUnderstanding] LLM initialization warning: {e}")
            _understanding_chat = None
    return _understanding_chat


# --------------------------------------------------
# Deterministic Fallback Logic
# --------------------------------------------------

ORDINAL_WORDS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
}

COUNT_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


def _extract_requested_field(text):
    text_clean = str(text or "").lower()
    if any(k in text_clean for k in ["official source", "source url", "source link", "source", "url", "official link", "link"]):
        return "source"
    if any(k in text_clean for k in ["deadline", "last date", "end date", "due date"]):
        return "deadline"
    if any(k in text_clean for k in ["issue date", "issued date", "when was it issued", "when was it published", "published date", "date of issue", "when was this issued"]):
        return "issue_date"
    if any(k in text_clean for k in ["reference number", "reference no", "ref no", "ref number", "reference"]):
        return "reference_number"
    if any(k in text_clean for k in ["application fee", "fees", "fee", "cost", "amount", "charge", "charges"]):
        return "fees"
    if any(k in text_clean for k in ["document", "documents", "docs", "certificate", "mark sheet", "photo", "verification guidelines"]):
        return "documents"
    if any(k in text_clean for k in ["eligibility", "eligible", "who can apply", "who is eligible"]):
        return "eligibility"
    if any(k in text_clean for k in ["where do i have to go", "where to report", "where", "location", "venue", "campus"]):
        return "location"
    if any(k in text_clean for k in ["when do students have to leave", "when will the hostel reopen", "when to report", "schedule", "timing", "time"]):
        return "time"
    if any(k in text_clean for k in ["procedure", "process", "steps", "how to apply"]):
        return "procedure"
    if any(k in text_clean for k in ["contact", "email", "phone", "helpline"]):
        return "contact"
    if any(k in text_clean for k in ["in details", "in detail", "tell me more", "explain it in detail", "explain it", "details", "summary", "summarize", "what does this notice say", "what does this mean"]):
        return "details"
    return None


def _extract_ordinal_from_text(text):
    text_clean = re.sub(r"[?.!,]+$", "", text.lower()).strip()

    # "first-round", "second round", "3rd semester" and "fourth year"
    # describe academic items, not positions in a previous notice list.
    if re.search(
        r"\b(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|"
        r"\d+(?:st|nd|rd|th))[-\s]+(?:round|semester|year|phase)\b",
        text_clean,
    ):
        return None

    # Do not match ordinal if text mentions an official entrance exam
    for topic_kw in ["wbjee", "wbjeeb", "jeca", "jelet", "jemat", "pget", "cet"]:
        if re.search(rf"\b{topic_kw}\b", text_clean):
            return None

    if re.search(r"\b(?:the\s+)?last\s+one\b", text_clean) or re.fullmatch(r"(?:show|tell\s+me\s+about\s+)?the\s+last(?:\s+one)?", text_clean):
        return -1

    # Pattern: "2nd notice", "the second one", "1st notification"
    words_pattern = "|".join(ORDINAL_WORDS.keys())
    p1 = re.search(r"\b(?:the\s+)?(\d+)(?:st|nd|rd|th)\s+(?:one|notice|notification|result|circular)?\b", text_clean)
    if p1:
        return int(p1.group(1))

    p2 = re.search(rf"\b(?:the\s+)?({words_pattern})\s+(?:one|notice|notification|result|circular)?\b", text_clean)
    if p2:
        return ORDINAL_WORDS[p2.group(1)]

    # Direct short command: "the second one", "show the 3rd", "tell me about the 2nd one"
    p3 = re.search(r"\b(?:second|third|fourth|fifth|first|2nd|3rd|4th|5th|1st)\b", text_clean)
    if p3 and ("tell" in text_clean or "show" in text_clean or "about" in text_clean or len(text_clean.split()) <= 4):
        matched = p3.group(0)
        if matched in ORDINAL_WORDS:
            return ORDINAL_WORDS[matched]
        digit_m = re.match(r"(\d+)", matched)
        if digit_m:
            return int(digit_m.group(1))

    return None


def _extract_count_from_text(text):
    text_lower = text.lower()

    m_atleast = re.search(r"\bat\s*least\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b", text_lower)
    if m_atleast:
        v = m_atleast.group(1)
        cnt = int(v) if v.isdigit() else COUNT_WORDS.get(v, 4)
        if 1 <= cnt <= 20:
            return cnt

    match = re.search(r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:latest|recent|new)\b", text_lower)
    if match:
        val = match.group(1)
        cnt = int(val) if val.isdigit() else COUNT_WORDS.get(val, 3)
        if 1 <= cnt <= 20:
            return cnt

    match_rev = re.search(r"\b(?:latest|recent|new)\s+(?:notices?\s+)?(?:at\s*least\s+)?(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b", text_lower)
    if match_rev:
        val = match_rev.group(1)
        cnt = int(val) if val.isdigit() else COUNT_WORDS.get(val, 3)
        if 1 <= cnt <= 20:
            return cnt

    match3 = re.search(r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:notices?|notifications?)\b", text_lower)
    if match3:
        val = match3.group(1)
        if val.isdigit():
            num = int(val)
            # CRITICAL: If num is a 4-digit year (e.g. 2024, 2025, 2026) or > 20, it is NOT a count!
            if 1 <= num <= 20:
                return num
        elif val in COUNT_WORDS:
            return COUNT_WORDS[val]

    m_any = re.search(r"\b(?:atleast|count\s*[:=]?)\s*(\d+)\b", text_lower)
    if m_any:
        num = int(m_any.group(1))
        if 1 <= num <= 20:
            return num

    # Explicit single notice request: "give only one notice", "show 1 notice", "single notice"
    if re.search(r"\b(?:only\s+one|single|1)\s+(?:notice|notification)\b", text_lower):
        return 1

    if re.search(r"\b(?:the\s+)?(?:most\s+recent|latest)\s+(?:official\s+)?(?:university\s+)?notice\b", text_lower) and not re.search(r"\b(?:notices|all)\b", text_lower):
        return 1

    # Singular notice query: e.g. "tell me about wbjee 2026 notice", "what is the wbjee notice"
    if re.search(r"\b(?:notice|notification)\b", text_lower) and not re.search(r"\b(?:notices|notifications|all|list)\b", text_lower):
        return 1

    return None


def _is_conversational_casual(text):
    """
    Detect greetings, identity questions, name declarations and conversational corrections,
    as well as casual temporal phrases that must NOT trigger retrieval.
    """
    text_clean = str(text or "").strip()
    text_lower = text_clean.lower()
    text_normalized = re.sub(r"[?.!,;:]+$", "", text_lower).strip()

    # 1. Name declarations and Conversational Corrections:
    # "Actually, correct it. My name is Farhan."
    # "Correct my name to Farhan."
    # "Actually, my name is Farhan."
    # "Can you correct what I said?"
    correction_signals = [
        r"\bcorrect\s+(?:my\s+name|it)\b",
        r"\bcorrection[\s,.:;]",
        r"\bcan\s+you\s+correct\s+what\s+i\s+(?:said|told)\b",
        r"\b(?:actually|no|wait)[,\s]+(?:my\s+name\s+is|call\s+me)\s+[a-zA-Z]+\b",
        r"\b(?:my\s+name\s+is|call\s+me)\s+[a-zA-Z]+\b",
        r"^(?:i\s+am|i['’]m)\s+[a-zA-Z]+(?:[ -][a-zA-Z]+)?[.!]?$",
    ]
    for p in correction_signals:
        if re.search(p, text_lower):
            # Verify this is not a university notice search about certificate corrections
            if not any(k in text_lower for k in ["certificate", "portal", "registration certificate", "marksheet", "admit card correction"]):
                return True

    # 2. Student identity & name query:
    if any(re.search(p, text_lower) for p in [
        r"\b(?:what(?:\s+is|\s*'s|s)?|tell\s+me)\b.*\bmy\s+name\b",
        r"\bwho\s+am\s+i\b",
        r"\bdo\s+you\s+(?:remember|know)\s+my\s+name\b",
    ]):
        return True

    # 3. Persona & pleasantries:
    if any(re.search(p, text_lower) for p in [
        r"\bwho\s+are\s+you\b",
        r"\bwhat\s+can\s+you\s+do\b",
        r"\bhow\s+can\s+you\s+help(?:\s+me)?\b",
        r"\b(?:thank\s+you|thanks)(?:\s+(?:very\s+much|a\s+lot|so\s+much))?$",
        r"^(?:ok|okay|cool|great|awesome|understood|got\s+it)$",
        r"^(?:hi|hello|hey|good\s+(?:morning|afternoon|evening))(?:\s+uniai)?(?:[,\s]+.*)?$",
    ]):
        if not any(k in text_lower for k in ["wbjee", "jeca", "notice", "circular", "exam", "admission", "deadline", "fees"]):
            return True

    # 4. False temporal triggers (casual temporal usage):
    # "Today I want to understand what you can do."
    # "I recently started using UniAI."
    if any(re.search(p, text_lower) for p in [
        r"\btoday\s+i\s+(?:want|would\s+like|need)\s+to\s+(?:understand|learn|know|ask|see|explore)\b",
        r"\bi\s+recently\s+(?:started|joined|began|tried)\b",
        r"\bi\s+(?:recently\s+)?started\s+using\b",
        r"\btoday\s+i\s+want\s+to\s+understand\b",
    ]):
        return True

    return False


def _detect_explicit_topic_or_entity(text):
    """Detect whether the current message explicitly introduces a university topic or entrance."""
    text_lower = text.lower()
    for top in ["wbjee", "wbjeeb", "jeca", "jelet", "jemat", "pget", "cet", "hostel", "durga puja", "holiday", "u-frams", "face registration", "m.pharm", "games", "sports"]:
        if re.search(rf"\b{re.escape(top)}\b", text_lower):
            return "wbjee" if top in ["wbjee", "wbjeeb"] else top
    return None


# Independent topic switch guard. Runs before and after the LLM classifier.
# Keywords are explicit subject markers; generic field words like "deadline"
# are deliberately omitted because they can refer to the current notice.
TOPIC_MARKERS = {
    "wbjee": r"\bwbjeeb?\b",
    "cet": r"\bcet\b",
    "jeca": r"\bjeca\b",
    "jelet": r"\bjelet\b",
    "pget": r"\bpget\b",
    "jemat": r"\b(?:wbjemat|jemat)\b",
    "hostel": r"\bhostels?\b",
    "registration": r"\bregistration\s+(?:portal|process|deadline|closing|closure)\b",
    "scholarship": r"\bscholarships?\b",
    "exam": r"\b(?:examination|exam|semester)\b",
    "placement": r"\b(?:placement|recruitment)\b",
    "ragging": r"\bragging\b",
    "vacant_seats": r"\bvacant\s+(?:b\.?\s*tech\s+)?seats?\b",
    "affiliation": r"\b(?:affiliation|non[\s-]?aicte)\b",
}


def explicitly_changes_notice_topic(question, active_notice):
    """True when an independent question names an entity absent from the active notice."""
    if not isinstance(active_notice, dict):
        return False
    q = str(question or '').lower()
    # A definite reference to the current notice takes precedence over generic topics;
    # an explicitly different named exam/category still overrides it.
    data = active_notice.get('structured_data') or {}
    active_text = ' '.join(str(v) for v in (
        active_notice.get('title', ''), data.get('title', ''),
        data.get('summary', ''), data.get('action_required', ''),
        data.get('target_audience', ''), data.get('key_points', ''),
    )).lower()

    explicit_years = set(re.findall(r'\b20\d{2}\b', q))
    notice_years = set(re.findall(r'\b20\d{2}\b', active_text))
    if explicit_years and notice_years and not explicit_years.issubset(notice_years):
        return True

    # Changing admission rounds should not silently reuse the previous
    # round's document (even when both concern the same WBJEEB year).
    def rounds(text):
        result = set()
        for number, aliases in {
            1: r"(?:1st|first)", 2: r"(?:2nd|second)",
            3: r"(?:3rd|third)", 4: r"(?:4th|fourth)",
        }.items():
            if re.search(rf"\b{aliases}[-\s]+round\b", text):
                result.add(number)
        return result

    asked_rounds, active_rounds = rounds(q), rounds(active_text)
    if asked_rounds and active_rounds and asked_rounds.isdisjoint(active_rounds):
        return True

    q_topics = {name for name, pattern in TOPIC_MARKERS.items()
                if re.search(pattern, q)}
    active_topics = {name for name, pattern in TOPIC_MARKERS.items()
                     if re.search(pattern, active_text)}
    return any(name not in active_topics for name in q_topics)


def _explicit_temporal_notice_request(text):
    """Handle explicit global latest/today/yesterday requests before follow-ups.

    Topic-qualified queries such as "latest hostel notice" must still route
    through topic search rather than return all university notices.
    """
    lower = str(text or "").lower()
    if _detect_explicit_topic_or_entity(lower):
        return None
    if not re.search(r"\b(?:notices?|notifications?|circulars?)\b", lower):
        return None
    if re.search(r"\b(?:today'?s|published\s+today|came\s+today)\b", lower):
        return "today_notices"
    if re.search(r"\b(?:yesterday'?s|published\s+yesterday|came\s+yesterday)\b", lower):
        return "yesterday_notices"
    if re.search(r"\b(?:latest|recent|most\s+recent)\b", lower):
        return "latest_notices"
    return None


def _temporal_result(text, intent):
    scope = {"today_notices": "today", "yesterday_notices": "yesterday",
             "latest_notices": "latest"}[intent]
    return QueryUnderstandingResult(
        intent=intent,
        standalone_query={
            "today_notices": "university notices published today",
            "yesterday_notices": "university notices published yesterday",
            "latest_notices": "latest university notices",
        }[intent],
        needs_retrieval=True, use_active_notice=False,
        temporal_scope=scope,
        count=_extract_count_from_text(str(text or "")),
    )


def fallback_understand_query(message: str, state=None) -> QueryUnderstandingResult:
    """
    Deterministic query understanding parser that executes when the LLM is unavailable
    or produces invalid output. Implements the strict priority rules:
    1. Casual chat / identity corrections / false temporal triggers -> casual_chat
    2. Explicit new topic/entity/year -> fresh retrieval
    3. Explicit ordinal references -> ordinal_followup
    4. Active notice follow-up -> notice_followup
    5. Temporal notice queries (today, yesterday, latest) -> temporal retrieval
    6. General notice / topic search -> retrieval
    """
    text = str(message or "").strip()
    text_lower = text.lower()
    text_clean = re.sub(r"[?.!,]+$", "", text_lower).strip()

    # --------------------------------------------------
    # Priority 0: Conversational Casual & Identity
    # --------------------------------------------------
    if _is_conversational_casual(text):
        return QueryUnderstandingResult(
            intent="casual_chat",
            standalone_query=text,
            needs_retrieval=False,
            use_active_notice=False,
        )

    # --------------------------------------------------
    # Priority 1: Explicit global latest/today/yesterday request
    # --------------------------------------------------
    temporal_intent = _explicit_temporal_notice_request(text)
    if temporal_intent:
        return _temporal_result(text, temporal_intent)

    # --------------------------------------------------
    # Priority 2: Explicit Ordinal Reference
    # --------------------------------------------------
    ordinal = _extract_ordinal_from_text(text)
    if ordinal is not None:
        last_records = state.get_last_notice_records() if state else []
        if ordinal == -1 and last_records:
            ordinal = len(last_records)
        elif ordinal == -1:
            ordinal = 1

        return QueryUnderstandingResult(
            intent="ordinal_followup",
            standalone_query=f"Details for notice #{ordinal}",
            needs_retrieval=False,
            use_active_notice=False,
            ordinal=ordinal,
        )

    # --------------------------------------------------
    # Detect Topic and Year in current query
    # --------------------------------------------------
    explicit_topic = _detect_explicit_topic_or_entity(text)
    year_match = None
    ym = re.search(r"\b(20\d{2})\b", text)
    if ym:
        year_match = int(ym.group(1))

    has_active_notice = bool(state and state.get_active_notice())
    active_doc = state.get_active_notice() if has_active_notice else None
    active_sd = active_doc.get("structured_data", {}) if active_doc else {}
    active_title = (active_sd.get("title") or active_doc.get("title") or "").lower() if active_doc else ""

    # Check if current query represents an EXPLICIT NEW TOPIC overriding active notice:
    # Example: active notice is "Hostel Closure", user says "What documents are required for WBJEE 2026?"
    is_explicit_override = explicitly_changes_notice_topic(text, active_doc)
    if has_active_notice and explicit_topic:
        active_searchable = " ".join(str(x) for x in (
            active_title, active_sd.get("summary", ""),
            active_sd.get("key_points", ""), active_sd.get("action_required", "")
        )).lower()
        if explicit_topic not in active_searchable:
            is_explicit_override = True

    # --------------------------------------------------
    # Priority 2: Active Notice Follow-Up (when not overriding)
    # --------------------------------------------------
    if has_active_notice and not is_explicit_override:
        req_field = _extract_requested_field(text)

        demonstrative_ref = any(term in text_lower for term in [
            "this notice", "that notice", "the notice", "this circular", "this notification",
            "about this", "of this", "for this", "about it", "of it", "for it", "in this",
            "same notice", "this one", "that one", "for that notice", "for this notice"
        ])

        followup_phrases = [
            "in details", "in detail", "tell me more", "explain more", "explain this",
            "what does this notice mean", "what does it mean", "summarize this", "summarize",
            "what is its deadline", "what is the deadline", "what is the last date",
            "what documents are needed", "what documents are required", "what documents do i need to bring",
            "what documents should i bring", "what documents do i need",
            "who is eligible", "what is the fee", "how much is the fee", "what is the application fee",
            "what is the source", "can you give me the official source", "official link", "official source",
            "when was it published", "when was it issued", "what is the reference number",
            "when do students have to leave", "when will the hostel reopen",
            "where do i have to go", "where to report", "what about eligibility"
        ]

        is_followup = (
            demonstrative_ref or
            (req_field is not None and len(text_clean.split()) <= 7 and not explicit_topic and not year_match) or
            any(phrase in text_clean for phrase in followup_phrases) and not (explicit_topic or year_match) or
            (len(text_clean.split()) <= 4 and not explicit_topic and not year_match)
        )

        if is_followup:
            title_ref = active_sd.get("title") or active_doc.get("title") or "the active notice"
            return QueryUnderstandingResult(
                intent="notice_followup",
                standalone_query=f"{text} regarding {title_ref}",
                needs_retrieval=False,
                use_active_notice=True,
                requested_field=req_field,
            )

    # --------------------------------------------------
    # Priority 3: Temporal Queries (Today / Yesterday / Latest)
    # --------------------------------------------------
    if re.search(r"\b(?:what\s+notices|any\s+notices?)\s+(?:came|published|released|issued)?\s+today\b", text_lower) or \
       re.search(r"\b(?:give\s+me|show\s+me)?\s*today'?s\s+notices?\b", text_lower) or \
       re.fullmatch(r"what university notices came today\??", text_clean):
        count = _extract_count_from_text(text)
        return QueryUnderstandingResult(
            intent="today_notices",
            standalone_query="university notices published today",
            needs_retrieval=True,
            temporal_scope="today",
            count=count,
        )

    if re.search(r"\b(?:what\s+notices|any\s+notices?)\s+(?:came|published|released|issued)?\s+yesterday\b", text_lower) or \
       re.search(r"\b(?:give\s+me|show\s+me)?\s*yesterday'?s\s+notices?\b", text_lower):
        count = _extract_count_from_text(text)
        return QueryUnderstandingResult(
            intent="yesterday_notices",
            standalone_query="university notices published yesterday",
            needs_retrieval=True,
            temporal_scope="yesterday",
            count=count,
        )

    latest_patterns = [
        r"\b(?:most\s+recent|latest)\s+(?:official\s+)?(?:university\s+)?notice\b",
        r"\b(?:latest|recent)\s+(?:official\s+)?(?:university\s+)?notices\b",
        r"\b\d+\s+(?:latest|recent)\s+(?:official\s+)?(?:university\s+)?(?:notices?|notifications?)\b",
        r"\b(?:give\s+me|show\s+me)\s+(?:\d+\s+)?(?:latest|recent)\b",
        r"\bwhat\s+are\s+the\s+recent\s+(?:university\s+)?notices\b",
        r"\b(?:most\s+recent|latest)\s+(?:university\s+)?notices?\b",
    ]
    if any(re.search(p, text_lower) for p in latest_patterns):
        count = _extract_count_from_text(text)
        if count is None and ("most recent" in text_lower or re.search(r"\blatest\s+(?:official\s+)?(?:university\s+)?notice\b", text_lower)):
            count = 1
        return QueryUnderstandingResult(
            intent="latest_notices",
            standalone_query="latest university notices",
            needs_retrieval=True,
            temporal_scope="latest",
            count=count,
        )

    # --------------------------------------------------
    # Priority 4: Topic Search
    # --------------------------------------------------
    if explicit_topic:
        count = _extract_count_from_text(text)
        if count is None and re.search(r"\b(?:last|latest|most recent)\b", text_lower):
            count = 1
        req_field = _extract_requested_field(text)
        return QueryUnderstandingResult(
            intent="topic_search",
            standalone_query=text,
            needs_retrieval=True,
            use_active_notice=False,
            topic=explicit_topic,
            year=year_match,
            count=count,
            requested_field=req_field,
        )

    # --------------------------------------------------
    # Priority 5: General Notice Search
    # --------------------------------------------------
    req_field = _extract_requested_field(text)
    return QueryUnderstandingResult(
        intent="notice_search",
        standalone_query=text,
        needs_retrieval=True,
        use_active_notice=False,
        year=year_match,
        count=_extract_count_from_text(text),
        requested_field=req_field,
    )


# --------------------------------------------------
# Main Entry Point
# --------------------------------------------------

def understand_query(message: str, state=None) -> QueryUnderstandingResult:
    """
    Main Query Understanding entry point.
    First attempts to classify and parse structured intent using LLM.
    If LLM generation fails or produces malformed JSON, falls back safely to
    the robust deterministic parser.
    """
    if not message or not str(message).strip():
        return QueryUnderstandingResult(
            intent="casual_chat",
            standalone_query="",
            needs_retrieval=False,
        )

    # Deterministic plural reference: MUST take precedence over the LLM's
    # topic_search classification (e.g. "these two hostel deadlines").
    if state is not None and len(state.get_last_answer_records()) >= 2:
        if re.search(r"\b(these|those|both|the two|two|which of them|which one)\b", message, re.I) and re.search(
            r"\b(deadlines?|notices?|dates?|documents?|applications?|comes? first|earlier|later|difference|compare|days?)\b", message, re.I
        ) and not re.search(r"\b(?:show|find|search|retrieve)\s+(?:me\s+)?(?:new|other|latest)\b", message, re.I):
            return QueryUnderstandingResult(
                intent="multi_notice_followup", standalone_query=message,
                needs_retrieval=False, use_active_notice=False,
                count=len(state.get_last_answer_records()),
            )

    # Fast deterministic check for obvious casual / conversational correction:
    # Ensures instant zero-latency handling and prevents LLM misclassifications on greetings & corrections
    if _is_conversational_casual(message):
        return QueryUnderstandingResult(
            intent="casual_chat",
            standalone_query=message,
            needs_retrieval=False,
            use_active_notice=False,
        )

    # Explicit global time queries must never inherit an old active notice.
    temporal_intent = _explicit_temporal_notice_request(message)
    if temporal_intent:
        return _temporal_result(message, temporal_intent)

    # Fast deterministic check for clear ordinal requests:
    ordinal = _extract_ordinal_from_text(message)
    if ordinal is not None:
        last_records = state.get_last_notice_records() if state else []
        if ordinal == -1 and last_records:
            ordinal = len(last_records)
        elif ordinal == -1:
            ordinal = 1
        return QueryUnderstandingResult(
            intent="ordinal_followup",
            standalone_query=f"Details for notice #{ordinal}",
            needs_retrieval=False,
            use_active_notice=False,
            ordinal=ordinal,
        )

    # Hard guarantee: an explicit switch (CET registration after hostel, etc.)
    # cannot be overridden by a mistaken LLM notice_followup classification.
    active = state.get_active_notice() if state else None
    if explicitly_changes_notice_topic(message, active):
        fresh = fallback_understand_query(message, state)
        if fresh.intent == "notice_followup":
            fresh = QueryUnderstandingResult(
                intent="notice_search", standalone_query=message,
                needs_retrieval=True, use_active_notice=False,
                year=int(re.search(r"\b20\d{2}\b", message).group())
                if re.search(r"\b20\d{2}\b", message) else None,
            )
        return fresh

    # Deterministic handling of unambiguous active-notice follow-ups avoids
    # unnecessary LLM requests and prevents the model from changing the topic.
    if active is not None and not explicitly_changes_notice_topic(message, active):
        deterministic = fallback_understand_query(message, state)
        if deterministic.intent == "notice_followup":
            return deterministic

    model = get_understanding_model()
    if model is None:
        return fallback_understand_query(message, state)

    # Format state for LLM
    state_context = state.format_context_for_understanding(max_turns=3) if state else "None"
    prompt_input = f"STUDENT MESSAGE:\n\"{message}\"\n\nCONVERSATION STATE:\n{state_context}\n\nJSON OUTPUT:"

    try:
        response = model.invoke([
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=prompt_input),
        ])

        content = response.content if hasattr(response, "content") else str(response)
        if isinstance(content, list):
            content = "".join(str(p) for p in content)

        content = content.strip()
        if "```" in content:
            matches = re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
            if matches:
                content = matches[0].strip()

        start_idx = content.find("{")
        end_idx = content.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            json_str = content[start_idx:end_idx + 1]
            data = json.loads(json_str)

            # Validate with Pydantic, then enforce context invariants. The
            # LLM must not fabricate an active notice or override explicit
            # topic/year switches selected by deterministic safeguards.
            validated = QueryUnderstandingResult.model_validate(data)
            if validated.use_active_notice or validated.intent == "notice_followup":
                if active is None or explicitly_changes_notice_topic(message, active):
                    return fallback_understand_query(message, state)
            explicit_year = re.search(r"\b(20\d{2})\b", message)
            if explicit_year and validated.year is not None:
                if validated.year != int(explicit_year.group(1)):
                    return fallback_understand_query(message, state)
            return validated

    except Exception:
        pass

    return fallback_understand_query(message, state)
