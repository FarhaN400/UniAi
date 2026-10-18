# 🎓 Module 4 — Conversational RAG & Multi-Turn Student Assistant

> **University AI Assistant (UniAI) — MAKAUT**  
> Context-aware, anti-hallucination Retrieval-Augmented Generation (RAG) assistant for official university circulars, notices, admission guidelines, and academic schedules.

Module 4 is the interactive conversational engine and user-facing intelligence layer of **UniAI**. It unites the data collected in Module 1, structured in Module 2, and indexed in Module 3 into an intelligent, multi-turn assistant capable of answering complex student queries with zero hallucinations and verified official citations.

---

## 🎯 Key Objectives

1. **Anti-Hallucination Guarantee:** Answers are strictly grounded in official notices retrieved from MongoDB and Pinecone. The assistant will never invent deadlines, fees, document checklists, or eligibility criteria.
2. **Context-Aware Multi-Turn Conversations:** Maintains conversational state across turns, enabling seamless follow-up questions (e.g., *"tell me more about this notice"*, *"what is its deadline?"*, *"now show the 3rd one"*, *"which of these two deadlines comes first?"*).
3. **Intelligent Query Understanding Layer:** Classifies student intent into distinct operational categories (casual chat, latest notices, specific field inquiries, topic searches, ordinal follow-ups, and multi-notice comparisons) while handling student identity declarations and corrections.
4. **Dual-Path Hybrid Retrieval:** Seamlessly blends serverless Pinecone vector search with MongoDB date-based temporal retrieval and lexical reranking.
5. **Direct Source Verification:** Every response referencing a notice provides the official MAKAUT document title, relevant dates, and the direct PDF source URL.

---

## 🏗️ Architecture & Query Flow

```text
                                Student Query
                                      │
                                      ▼
                   ┌──────────────────────────────────────┐
                   │       ConversationState (Memory)     │
                   │  - Session Turns & History Window    │
                   │  - Active Notice & Last Notice List  │
                   │  - Last Cited Answer Records         │
                   │  - Student Identity & Name Memory    │
                   └──────────────────┬───────────────────┘
                                      │
                                      ▼
                   ┌──────────────────────────────────────┐
                   │     Query Understanding Layer        │
                   │     (Qwen 3 4B-Instruct / Heuristic) │
                   │  - Intent Classification (9 types)   │
                   │  - Standalone Query Rewriting        │
                   │  - Temporal Scope & Year Extraction  │
                   │  - Field & Ordinal Detection         │
                   │  - Topic Switch Detection            │
                   └──────────────────┬───────────────────┘
                                      │
              ┌───────────────────────┼───────────────────────┐
              ▼                       ▼                       ▼
      [Casual Chat]          [Active Follow-up]       [Fresh Retrieval]
    - Greeting/Persona      - Same Active Notice     - retrieve_context()
    - Student Name Memory     (Bypasses Search)               │
              │                       │                       │
              │                       │        ┌──────────────┴──────────────┐
              │                       │        ▼                             ▼
              │                       │  [Time-Based]                [Semantic Hybrid]
              │                       │  - Latest notices            - Pinecone Vector Search
              │                       │  - Today / Yesterday         - Metadata Year Filtering
              │                       │  - Chronological sort        - Lexical Reranker Overlap
              │                       │        │                     - MongoDB Hydration & Fallback
              │                       │        │                             │
              │                       └────────┼─────────────────────────────┘
              │                                │
              ▼                                ▼
     Direct Response              Retrieved Notice Context
                                               │
                                               ▼
                              ┌──────────────────────────────────┐
                              │     Anti-Hallucination Prompt    │
                              │   + Qwen 3 4B-Instruct via Ollama│
                              └────────────────┬─────────────────┘
                                               │
                                               ▼
                                   Grounded Student Answer
                                 + Verified Official PDF Link
```

---

## 🧩 Core Components

### 1. Conversational State Manager (`conversation_state.py`)

The `ConversationState` class manages conversational context throughout a session:

- **`chat_history`:** Stores recent interaction turns `(query, response, records)` within a sliding window (default: 5 turns).
- **`last_notice_records`:** Stores the list of notices retrieved from the most recent query.
- **`last_answer_records`:** Tracks only the notices **actually cited** in the assistant's response. This guarantees that multi-document comparisons (e.g., comparing two notices out of five candidates) compare the exact two notices discussed.
- **`active_notice` & `active_notice_id`:** Tracks the single notice currently in focus. Automatically set when a query returns a single notice, and automatically cleared when a list of notices is presented.
- **`session_memory` (Identity & Corrections):** Remembers student name declarations and conversational corrections (e.g., *"My name is Farhan"*, *"Call me Farhan"*, *"Correct my name to Farhan"*).
- **Context Summarization:**
  - `format_recent_history(max_turns)`: Formats conversational turns for the RAG generation prompt.
  - `format_context_for_understanding(max_turns)`: Formats a structured summary for the Query Understanding layer.

---

### 2. Query Understanding Layer (`query_understanding.py`)

Before executing any retrieval or LLM generation, student input is parsed by the Query Understanding Layer powered by `qwen3:4b-instruct` (with deterministic fallback heuristics).

#### Intent Classification Schema:
| Intent | Description | Example Query | Action Taken |
|---|---|---|---|
| `casual_chat` | Greetings, bot persona, student identity | *"Hello UniAI, my name is Farhan"* / *"What is my name?"* | Responds conversationally; zero retrieval; updates session name. |
| `latest_notices` | General latest notice queries with optional count | *"Give me 5 latest notices"* | Routes to MongoDB temporal sorting with `count=5`. |
| `today_notices` | Circulars published today | *"What notices came today?"* | Filters notices where `issue_date` matches today's date. |
| `yesterday_notices` | Circulars published yesterday | *"Show notices published yesterday"* | Filters notices where `issue_date` matches yesterday's date. |
| `topic_search` | Search filtered by topic | *"Hostel seat allotment notices"* | Searches MongoDB structured titles and body texts for the topic. |
| `notice_search` | General information question | *"What documents are needed for WBJEE 2026?"* | Executes hybrid semantic retrieval with year-aware filtering. |
| `notice_followup` | Follow-up on the active notice | *"What is its deadline?"* / *"Where do I report?"* | Contextual answer generated from the active notice; skips vector search. |
| `ordinal_followup` | Selecting an item from a prior list | *"Now the 3rd one"* / *"Explain the second notice"* | Extracts notice at index $N-1$ from `last_notice_records`. |
| `multi_notice_followup` | Comparing previously cited notices | *"Which of these two deadlines comes first?"* | Reuses the exact documents in `last_answer_records`. |

#### Topic Switch Detection:
The helper `explicitly_changes_notice_topic` prevents the assistant from remaining locked to an active notice when the student introduces a new topic or different year. For example, if discussing a hostel notice and the student asks *"What documents are needed for WBJEE 2026 admission?"*, the system detects the topic switch and triggers fresh retrieval.

---

### 3. Dual-Path Retrieval Engine (`retrieve.py`)

The retrieval router `retrieve_context(question, top_k)` directs queries through specialized retrieval pipelines:

#### A. Temporal Retrieval (`retrieve_time_based`)
- Directly queries MongoDB `university_documents` for notices with `status: "processed"`.
- Parses official notice dates (`issue_date` in formats `%d-%m-%Y` and `%d-%m-%Y %H:%M`), falling back to `detected_at`.
- Supports exact calendar filtering for **Today** and **Yesterday**, as well as reverse-chronological sorting for **Latest** notices.

#### B. Semantic Vector Retrieval with Metadata & Lexical Reranking (`retrieve_semantic`)
1. **Year Extraction & Metadata Filtering:**
   - Extracts 4-digit years from the query (e.g., `2025`, `2026`).
   - Queries Pinecone serverless index `uniai` (namespace `notices`) with metadata filter `{"year": {"$eq": year}}`.
   - **Filter Recovery:** If zero hits are returned with the filter (e.g., due to missing or differently typed metadata), automatically retries without the filter and verifies year against document content (`_document_year_matches`).
2. **MongoDB Document Hydration:**
   - Maps Pinecone hit IDs to MongoDB documents, retrieving the full `structured_data`, `raw_text`, and source URL.
3. **Lexical Reranking (`_lexical_score`):**
   - Computes keyword overlap between query tokens and notice title/body/key points.
   - Applies domain-specific scoring adjustments (e.g., boosting documents matching *"verification"* and *"documents"* while penalizing general registration portal notices).
4. **Legacy MongoDB Fallback:**
   - For notices missing from the vector index, a targeted regex search on MongoDB title and summary ensures legacy notices are never dropped.
5. **Candidate Pruning:**
   - Evaluates 15–40 candidates and returns the top 5 highest-ranked notices for LLM generation.

---

### 4. Anti-Hallucination Prompt & Generation (`prompt.py` & `main.py`)

The system prompt enforces rigorous academic constraints:
- **Strict Grounding:** The assistant must answer using **ONLY** the provided context. Outside common sense, assumptions, or fabricated figures are strictly forbidden.
- **Exact Fallback:** If the retrieved notices do not contain the answer, the LLM must respond with:
  > *"I could not find this information in the available university notices."*
- **Single-Line Multi-Notice Format:** When multiple notices are retrieved, they are formatted as:
  > `**Headline** | Date: DD-MM-YYYY | Key detail: ... | Source: https://...`
- **Source Citation:** Every answer includes the official PDF source link for student verification.
- **Citation Filtering:** Only notices whose URLs are explicitly mentioned in the generated answer are retained in `last_answer_records`.

---

## 📂 File Structure

| File | Description |
|---|---|
| [`main.py`](file:///Users/farhanakhtar/Desktop/Project/UniAi/Module4/main.py) | **Main Assistant Orchestrator & CLI:** Integrates state management, query understanding, retrieval, RAG chain invocation, response formatting, and citation tracking. |
| [`retrieve.py`](file:///Users/farhanakhtar/Desktop/Project/UniAi/Module4/retrieve.py) | **Retrieval Engine:** Pinecone semantic search, year filtering and fallback, lexical reranker, MongoDB document hydration, and temporal retrieval. |
| [`query_understanding.py`](file:///Users/farhanakhtar/Desktop/Project/UniAi/Module4/query_understanding.py) | **Query Understanding Layer:** Pydantic schema for 9 query intents, LLM-based intent parser, topic switch detector, and fallback heuristics. |
| [`conversation_state.py`](file:///Users/farhanakhtar/Desktop/Project/UniAi/Module4/conversation_state.py) | **Session Memory & State:** Multi-turn chat history, active notice tracking, cited records management, and student name memorization/correction. |
| [`prompt.py`](file:///Users/farhanakhtar/Desktop/Project/UniAi/Module4/prompt.py) | **Prompt Engineering:** Strict anti-hallucination LangChain prompt template enforcing verified citations and concise student answers. |
| [`README_FIXES.md`](file:///Users/farhanakhtar/Desktop/Project/UniAi/Module4/README_FIXES.md) | Historical patch notes documenting query classification and Pinecone fallback fixes. |

---

## ⚙️ Environment Configuration

Module 4 requires credentials in the root `.env` file:

```env
MONGO_URI=mongodb+srv://<username>:<password>@cluster0.mongodb.net/?retryWrites=true&w=majority
PINECONE_API_KEY=pcsk_...
```

### Local LLM Requirement (Ollama)
Module 4 uses **Qwen 3 4B-Instruct** running locally via Ollama:

```bash
# Verify Ollama is running and pull the model
ollama run qwen3:4b-instruct
```

---

## ▶️ How to Run

### 1. Interactive Assistant (CLI)

```bash
cd /Users/farhanakhtar/Desktop/Project/UniAi/Module4
python3 main.py
```

### 2. Debug Mode

To inspect intent parsing, Pinecone hit scores, lexical reranking, and follow-up routing in real-time, set `UNIAI_DEBUG=1`:

```bash
UNIAI_DEBUG=1 python3 main.py
```

---

## 💬 Example Interactive Conversations

### Example 1: Multi-Turn Exploration with Ordinal Selection

```text
🎓 UniAI — University AI Assistant
Type 'exit' to stop.

You: Give me 3 latest notices

UniAI: 1. Notice Regarding Semester Examination Form Fill-up 2026
Date: 15-09-2026
Reference: COE/MAKAUT/2026/089
Summary: Students are required to submit examination forms online before the deadline.
Official source: https://makautwb.ac.in/datas/users/0-exam_form_2026.pdf

2. Notification for WBJEE Reporting 2026
Date: 11-09-2026
Reference: REG/WBJEE/2026/012
Summary: Schedule and document verification instructions for candidate reporting.
Official source: https://makautwb.ac.in/datas/users/0-wbjee_reporting_2026.pdf

3. Campus Discipline and Gate Regulations
Date: 07-09-2026
Summary: Directives prohibiting the obstruction of university entry and administrative offices.
Official source: https://makautwb.ac.in/datas/users/0-discipline.pdf

You: Now the second one

UniAI: Notification for WBJEE Reporting 2026
Date: 11-09-2026
Reference: REG/WBJEE/2026/012
Summary: Schedule and document verification instructions for candidate reporting.
Official source: https://makautwb.ac.in/datas/users/0-wbjee_reporting_2026.pdf

You: What documents do I need to bring?

UniAI: According to the WBJEE Reporting notice, candidates must bring:
1. WBJEE 2026 Rank Card & Allotment Letter
2. Class 10 & 12 Marksheets and Admit Cards
3. Category & Domicile Certificates (if applicable)
4. Anti-ragging declaration and Medical Fitness Certificate.

Source: https://makautwb.ac.in/datas/users/0-wbjee_reporting_2026.pdf
```

### Example 2: Notice Comparison & Date Arithmetic

```text
You: Compare the hostel closure notice and the hostel seat application notice issued in 2026. What are their respective deadlines?

UniAI: **Hostel Seat Application Notice** | Date: 16-10-2026 | Key detail: Students must fill out the Google Form by 16 October 2026 to apply for hostel accommodation. | Source: https://makautwb.ac.in/datas/users/0-googlfrom26.pdf
**Hostel Closure Notice** | Date: 14-10-2026 | Key detail: All hostel boarders must vacate their rooms by 14 October 2026, preferably by 01:00 p.m. | Source: https://makautwb.ac.in/datas/users/0-notice_holiday26.pdf

You: Which of these two hostel deadlines comes first, and by how many days?

UniAI: The Hostel Closure Notice deadline comes first on 14 October 2026, while the Hostel Seat Application deadline is on 16 October 2026. The difference is 2 days.
```

### Example 3: Conversational Memory & Name Correction

```text
You: Hello, my name is Farha.

UniAI: Got it, Farha! How can I assist you with MAKAUT notices today?

You: Actually, correct my name to Farhan.

UniAI: Got it, Farhan! How can I assist you with MAKAUT notices today?

You: What is my name?

UniAI: Your name is Farhan.
```

---

## ✅ Quality & Robustness Highlights

- [x] **Zero Hallucination:** Strict prompt instructions and fallback prevent fabricated answers when notice content is unavailable.
- [x] **Dual Retrieval Paths:** Distinguishes temporal queries (latest/today/yesterday) from semantic topic queries.
- [x] **Resilient Year Filtering:** Automatic recovery without Pinecone metadata filters ensures notices are never dropped due to schema mismatches.
- [x] **Lexical Reranker:** Token overlap scoring prevents document confusion (e.g., distinguishing admission verification from registration closure).
- [x] **Active Notice Continuity:** Contextual follow-up queries do not re-run full vector searches when the active notice is already in session.
- [x] **Topic Switch Detection:** Automatically detects when a student shifts to a new topic or academic year, preventing stale context contamination.
- [x] **Exact Citation Tracking:** Preserves only the notices cited in assistant answers for subsequent multi-document comparisons.
- [x] **Verified Official Links:** Every factual answer cites the official university PDF URL.
