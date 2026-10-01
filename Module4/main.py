import os
import sys
import re
from dotenv import load_dotenv

from langchain_huggingface import (
    HuggingFaceEndpoint,
    ChatHuggingFace
)

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

try:
    from .retrieve import retrieve_context, retrieve_topic_notices, build_context_string
    from .prompt import rag_prompt
except ImportError:
    from retrieve import retrieve_context, retrieve_topic_notices, build_context_string
    from prompt import rag_prompt


def extract_requested_count(question):
    """Extract a user-requested record count from latest/recent notice questions."""
    text = str(question or "").lower()
    if not is_latest_notice_query(text):
        return None

    match = re.search(r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b", text)
    if not match:
        return None

    count_words = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    }
    count = int(match.group(1)) if match.group(1).isdigit() else count_words[match.group(1)]
    return max(1, min(count, 10))


def is_latest_notice_query(question):
    text = str(question or "").lower()
    return any(keyword in text for keyword in [
        "latest", "recent", "new notice", "new notices",
        "new notification", "new notifications",
    ])


def extract_notice_ordinal(question):
    """Extract a requested notice position, such as '5th' or 'fifth one'."""
    text = str(question or "").lower()
    match = re.search(r"\b(\d+)(?:st|nd|rd|th)\b", text)
    if match:
        return max(1, min(int(match.group(1)), 10))

    ordinal_words = {
        "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
        "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
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
    return bool(re.search(r"\b(?:last|latest|most recent)\s+(?:official\s+)?(?:notice|notification|news)\b", text))


def is_single_notice_follow_up(question):
    text = re.sub(r"[?.!,]+$", "", str(question or "").lower().strip())
    pattern = r"(?:(?:please\s+)?(?:give|show|list|send)(?:\s+me)?\s+)?(?:(?:just|only)\s+)?(?:one|1)(?:\s+(?:notice|notification|result))?"
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
        if len(details) > 200:
            details = details[:197].rsplit(" ", 1)[0] + "..."
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


load_dotenv()


# --------------------------------------------------
# LLM
# --------------------------------------------------

llm = HuggingFaceEndpoint(
    repo_id="openai/gpt-oss-120b",
    task="text-generation"
)

model = ChatHuggingFace(llm=llm)


# --------------------------------------------------
# RAG Chain
# --------------------------------------------------

rag_chain = rag_prompt | model


# --------------------------------------------------
# Chat History (in-memory for now)
# --------------------------------------------------
# This is temporary local session memory.
# Later, this can be moved to a per-user Atlas collection.
chat_history = []
last_latest_question = None
last_notice_records = []


def answer_from_records(question, records):
    """Generate an answer using the supplied notices and recent conversation."""
    context = build_context_string(records)
    recent_context = "\n".join(
        [f"User: {q}\nAssistant: {a}" for q, a in chat_history[-5:]]
    ) if chat_history else "No recent conversation history."

    try:
        response = rag_chain.invoke({
            "context": context,
            "question": question,
            "history": recent_context,
        })

        if hasattr(response, "content"):
            content = response.content
        elif isinstance(response, dict):
            content = response.get("content") or response.get("text") or str(response)
        else:
            content = str(response)

        if isinstance(content, list):
            content = "".join(str(part) for part in content)

        chat_history.append((question, content))
        return content
    except Exception as e:
        print(f"LLM generation failed: {e}")
        return "Sorry, I couldn't generate an answer at the moment."


# --------------------------------------------------
# UniAI
# --------------------------------------------------

def ask_uniai(question):
    """Ask a university notice question and return the final answer."""
    global last_latest_question, last_notice_records

    if not question or not str(question).strip():
        return "Please enter a question."

    if is_single_notice_follow_up(question) and last_notice_records:
        content = format_notice_line(last_notice_records[0])
        chat_history.append((question, content))
        return content

    if is_notice_detail_follow_up(question) and last_notice_records:
        return answer_from_records(question, last_notice_records[:1])

    topic = extract_supported_topic(question)
    if topic and is_latest_topic_notice_query(question):
        try:
            records = retrieve_topic_notices(topic, top_k=1)
        except Exception as e:
            print(f"Retrieval failed: {e}")
            return "I could not find this information in the available university notices."

        if not records:
            return "I could not find this information in the available university notices."

        last_notice_records = records
        content = format_notice_line(records[0])
        chat_history.append((question, content))
        return content

    ordinal = extract_notice_ordinal(question)
    if ordinal is not None:
        source_question = last_latest_question or "latest notices"
        try:
            records = retrieve_context(source_question, top_k=ordinal)
        except Exception as e:
            print(f"Retrieval failed: {e}")
            return "I could not find this information in the available university notices."

        if len(records) < ordinal:
            return f"I found only {len(records)} latest notices, so notice {ordinal} is not available."

        content = format_notice_line(records[ordinal - 1])
        chat_history.append((question, content))
        return content

    is_latest_query = is_latest_notice_query(question)
    requested_top_k = extract_requested_count(question)
    if requested_top_k is None:
        requested_top_k = 3

    try:
        # Step 1: Retrieve relevant university notices
        records = retrieve_context(question, top_k=requested_top_k)
    except Exception as e:
        print(f"Retrieval failed: {e}")
        return "I could not find this information in the available university notices."

    # Step 2: Handle no results
    if not records:
        return "I could not find this information in the available university notices."

    last_notice_records = records

    if is_latest_query:
        last_latest_question = question
        content = format_notice_list(records)
        chat_history.append((question, content))
        return content

    return answer_from_records(question, records)


# --------------------------------------------------
# Test
# --------------------------------------------------

if __name__ == "__main__":

    print("\n🎓 UniAI — University AI Assistant")
    print("Type 'exit' to stop.\n")

    while True:

        question = input("You: ").strip()

        if question.lower() in ["exit", "quit"]:
            print("UniAI: Goodbye! 👋")
            break

        if not question:
            continue

        answer = ask_uniai(question)

        print(f"\nUniAI: {answer}\n")