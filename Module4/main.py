import os
import sys
import re

from langchain_ollama import ChatOllama

if __package__:
    from .prompt import rag_prompt
    from .retrieve import (
        build_context_string,
        retrieve_context,
        retrieve_topic_notices,
    )
    from .conversation_state import ConversationState
    from .query_understanding import understand_query, QueryUnderstandingResult, explicitly_changes_notice_topic
else:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)

    from prompt import rag_prompt
    from retrieve import build_context_string, retrieve_context, retrieve_topic_notices
    from conversation_state import ConversationState
    from query_understanding import understand_query, QueryUnderstandingResult, explicitly_changes_notice_topic


MODEL_NAME = "qwen3:4b-instruct"
NO_RESULTS_MESSAGE = (
    "I could not find this information in the available university notices."
)


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
    num_ctx=4096,
    num_predict=1500,
    keep_alive="1m",
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


def answer_from_records(question, records, active_notice=None):
    """Generate an answer using the supplied notices and recent conversation."""
    _sync_state()
    context = build_context_string(records)
    recent_context = state.format_recent_history(max_turns=2)

    try:
        response = rag_chain.invoke(
            {
                "context": context,
                "question": question,
                "history": recent_context,
            }
        )
        if hasattr(response, "content"):
            content = response.content
        elif isinstance(response, dict):
            content = response.get("content") or response.get("text") or str(response)
        else:
            content = str(response)

        if isinstance(content, list):
            content = "".join(str(part) for part in content)

        # Keep only the notices actually cited in the generated answer.
        # A 5-document evidence set must not become "these five notices" when
        # the answer only discussed two of them.
        cited = [r for r in records if r.get("url") and str(r["url"]) in content]
        # Preserve the order of first appearance in the answer.
        cited.sort(key=lambda r: content.find(str(r["url"])))
        if not cited and len(records) == 1 and NO_RESULTS_MESSAGE not in content:
            cited = list(records)
        state.append_turn(question, content, records=cited, active_notice=active_notice if len(cited) == 1 else None)
        _sync_back()
        return content
    except Exception as error:
        print(f"LLM generation failed: {error}")
        return "Sorry, I couldn't generate an answer at the moment."


def _handle_casual_chat(question):
    """Produce conversational answers for casual chat, greetings, and identity queries."""
    text_lower = question.lower().strip()

    # Identity query: "what is my name", "who am i"
    if any(re.search(p, text_lower) for p in [r"\b(?:what(?:\s+is|\s*'s|s)?|tell\s+me)\b.*\bmy\s+name\b", r"\bwho\s+am\s+i\b", r"\bdo\s+you\s+(?:remember|know)\s+my\s+name\b"]):
        user_name = state.get_user_name()
        if user_name:
            return f"Your name is {user_name}."
        return "I don't know your name yet. Feel free to introduce yourself anytime!"

    # Identity declaration / correction
    current_name = state.extract_and_remember_user_name(question)
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
    user_name = state.get_user_name()
    greeting_suffix = f", {user_name}" if user_name else ""
    return f"Hello{greeting_suffix}! I am UniAI, your assistant for MAKAUT university notices. How can I help you today?"


def ask_uniai(question):
    """Ask a university notice question and return the final answer."""
    global last_latest_question, last_notice_records, chat_history

    if not question or not str(question).strip():
        return "Please enter a question."

    _sync_state()

    # Fast path: Follow-up requesting single notice or detail when active notice exists
    if is_single_notice_follow_up(question) and (state.get_active_notice() or state.get_last_notice_records()):
        active = state.get_active_notice() or state.get_last_notice_records()[0]
        content = format_notice_line(active)
        state.append_turn(question, content, records=[active], active_notice=active)
        _sync_back()
        return content

    if (is_notice_detail_follow_up(question)
            and (state.get_active_notice() or state.get_last_notice_records())
            and not explicitly_changes_notice_topic(
                question, state.get_active_notice() or state.get_last_notice_records()[0])):
        active = state.get_active_notice() or state.get_last_notice_records()[0]
        return answer_from_records(question, [active], active_notice=active)

    # Query Understanding Layer
    parsed = understand_query(question, state)

    # Multi-document follow-ups must reuse EXACTLY the documents referenced
    # by the previous answer, not the Pinecone candidate pool.
    if parsed.intent == "multi_notice_followup":
        prior = state.get_last_answer_records()
        if os.getenv("UNIAI_DEBUG", "0") == "1":
            print("[UniAI] multi-notice follow-up; reused notice IDs:",
                  [r.get("notice_id") for r in prior])
        if len(prior) >= 2:
            return answer_from_records(question, prior)
        return "I need the two notices to compare. Please ask me to show them first."

    # 1. Casual Chat
    if parsed.intent == "casual_chat":
        content = _handle_casual_chat(question)
        state.append_turn(question, content)
        _sync_back()
        return content

    # 2. Ordinal Follow-up ("now the 5th one", "show the second one")
    if parsed.intent == "ordinal_followup":
        ordinal = parsed.ordinal or extract_notice_ordinal(question) or 1
        last_records = state.get_last_notice_records()

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
        state.append_turn(question, content, records=[selected_record], active_notice=selected_record)
        _sync_back()
        return content

    # 3. Active Notice Follow-up. A new explicit year/topic must trigger fresh search.
    active_record = state.get_active_notice()
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
    if not active_record and state.get_last_notice_records():
        topic_switch = explicitly_changes_notice_topic(
            question, state.get_last_notice_records()[0]
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
        print("Active notice ID:", state.get_active_notice_id())
        print("Last notice count:", len(state.get_last_notice_records()))

    if (parsed.intent == "notice_followup" or parsed.use_active_notice) and not (conflicting_year or conflicting_topic):
        active = state.get_active_notice() or (state.get_last_notice_records() or [None])[0]
        if active:
            if os.getenv("UNIAI_DEBUG", "0").lower() in ("1", "true", "yes"):
                print("Follow-up route: active notice")
                print("Selected notice ID:", active.get("notice_id"))
                print("Selected notice title:", active.get("title"))
                print("Structured data:", active.get("structured_data"))
                print("Source URL:", active.get("url"))
            return answer_from_records(question, [active], active_notice=active)
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
            state.append_turn(question, content, records=records, active_notice=records[0])
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
        retrieval_k = requested_top_k if is_latest_query else max(12, requested_top_k)
        records = retrieve_context(search_query, top_k=retrieval_k)
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
            state.append_turn(question, content, records=records, active_notice=records[0])
            _sync_back()
            return content

        content = format_notice_list(records)
        state.append_turn(question, content, records=records, active_notice=None)
        _sync_back()
        return content

    active = records[0] if len(records) == 1 else None
    return answer_from_records(question, records, active_notice=active)


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
