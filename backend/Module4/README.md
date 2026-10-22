# 🎓 Module 4 — Conversational RAG & Multi-Turn Student Assistant

> **University AI Assistant (UniAI) — MAKAUT**  
> Context-aware, anti-hallucination Retrieval-Augmented Generation (RAG) assistant for official university circulars, examination notifications, admission schedules, and academic regulations.

Module 4 is the interactive conversational engine and user-facing intelligence layer of **UniAI**. It unites the data collected in Module 1, structured in Module 2, and indexed in Module 3 into an intelligent, multi-turn assistant capable of answering complex student queries with zero hallucinations, strict evidence verification, and verified official citations.

---

## 🎯 Key Objectives

1. **Anti-Hallucination Guarantee:** Answers are strictly grounded in official notices retrieved from MongoDB and Pinecone. The assistant will never invent deadlines, fees, document checklists, or eligibility criteria.
2. **Context-Aware Multi-Turn Conversations:** Maintains conversational state across turns, enabling seamless follow-up questions (e.g., *"tell me more about this notice"*, *"what is its deadline?"*, *"now show the 3rd one"*, *"which of these two deadlines comes first?"*).
3. **Intelligent Query Understanding Layer (`query_understanding.py`):** Classifies student intent into 9 distinct operational categories, resolves temporal constraints, detects topic switches, and handles student identity declarations and corrections.
4. **Dual-Path Hybrid Retrieval (`retrieve.py`):** Seamlessly blends serverless Pinecone dense vector search with MongoDB date-based temporal retrieval and Reciprocal Rank Fusion (RRF) lexical reranking.
5. **Rigorous Evidence Grounding (`evidence.py`):** Server-side validator checks generated claims against atomic evidence references, rejecting hallucinated figures, fabricated dates, or cross-document mixtures.
6. **Dual LLM Provider Support:** Supports high-speed cloud inference via **Groq** (`llama-3.3-70b-versatile`) and private local execution via **Ollama** (`qwen3:4b-instruct`).
7. **Direct Source Verification:** Every response referencing a circular provides the official MAKAUT document title, relevant dates, and the direct PDF source URL.

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
                   │  (Intent Classifier & Topic Switch)  │
                   │  - 9 Structured Intent Classes       │
                   │  - Standalone Query Rewriting        │
                   │  - Temporal Scope & Year Extraction  │
                   │  - Field & Ordinal Detection         │
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
              │                       │  - Chronological sort        - Lexical Reranker (RRF)
              │                       │        │                     - Admission Round Scoping
              │                       │        │                             │
              │                       └────────┼─────────────────────────────┘
              │                                │
              ▼                                ▼
     Direct Response              Retrieved Notice Context
                                               │
                                               ▼
                              ┌──────────────────────────────────┐
                              │     Evidence Bundle Builder      │
                              │     - Atomic Fact Refs (N1-E1)   │
                              │     - Context Compilation        │
                              └────────────────┬─────────────────┘
                                               │
                                               ▼
                              ┌──────────────────────────────────┐
                              │     Anti-Hallucination Prompt    │
                              │     + LLM (Groq / Ollama)        │
                              └────────────────┬─────────────────┘
                                               │
                                               ▼
                              ┌──────────────────────────────────┐
                              │     Server-Side Claim Validator  │
                              │  - Validates IDs & Evidence Refs │
                              │  - Eligibility Guard (AND vs OR) │
                              │  - Rejects Unsupported Figures   │
                              └────────────────┬─────────────────┘
                                               │
                                               ▼
                                   Grounded Student Answer
                                 + Verified Official PDF Link
```

---

## 🧩 Core Components

### 1. Conversational State Manager (`conversation_state.py`)

The `ConversationState` class manages conversational context throughout a student session:

- **`chat_history`:** Stores recent interaction turns `(query, response, records)` within a sliding window (default: 5 turns).
- **`last_notice_records`:** Stores the list of notices retrieved from the most recent query.
- **`last_answer_records`:** Tracks only the notices **actually cited** in the assistant's response. This guarantees that multi-document comparisons (e.g., comparing two notices out of five candidates) compare the exact two notices discussed.
- **`active_notice` & `active_notice_id`:** Tracks the single circular currently in focus. Automatically set when a query returns a single notice, and automatically cleared when a list of notices is presented.
- **`session_memory` (Identity & Corrections):** Remembers student name declarations and conversational corrections (e.g., *"My name is Farhan"*, *"Call me Farhan"*, *"Correct my name to Farhan"*).
- **Context Summarization:**
  - `format_recent_history(max_turns)`: Formats conversational turns for the RAG generation prompt.
  - `format_context_for_understanding(max_turns)`: Formats a structured summary for the Query Understanding layer.

---

### 2. Query Understanding Layer (`query_understanding.py`)

Before executing any retrieval or LLM generation, student input is analyzed by the Query Understanding Layer powered by the LLM with deterministic fallback heuristics.

#### Intent Classification Schema:
| Intent | Description | Example Query | Action Taken |
|---|---|---|---|
| `casual_chat` | Greetings, bot persona, student identity | *"Hello UniAI, my name is Farhan"* / *"What is my name?"* | Responds conversationally; zero retrieval; updates session name. |
| `latest_notices` | General latest notice queries with optional count | *"Give me 5 latest notices"* | Routes to MongoDB temporal sorting with `count=5`. |
| `today_notices` | Circulars published today | *"What notices came today?"* | Filters notices where `issue_date` matches today's date in Asia/Kolkata. |
| `yesterday_notices` | Circulars published yesterday | *"Show notices published yesterday"* | Filters notices where `issue_date` matches yesterday's date. |
| `topic_search` | Search filtered by topic | *"Hostel seat allotment notices"* | Searches MongoDB structured titles and body texts for the topic. |
| `notice_search` | General information question | *"What documents are needed for WBJEE 2026?"* | Executes hybrid semantic retrieval with year-aware filtering. |
| `notice_followup` | Follow-up on the active notice | *"What is its deadline?"* / *"Where do I report?"* | Contextual answer generated from the active notice; skips vector search. |
| `ordinal_followup` | Selecting an item from a prior list | *"Now the 3rd one"* / *"Explain the second notice"* | Extracts notice at index $N-1$ from `last_notice_records`. |
| `multi_notice_followup` | Comparing previously cited notices | *"Which of these two deadlines comes first?"* | Reuses the exact documents in `last_answer_records`. |

#### Topic Switch Detection (`explicitly_changes_notice_topic`):
Prevents the assistant from remaining locked to an active notice when the student introduces a new topic, entrance exam, or different year. For example, if discussing a hostel notice and the student asks *"What documents are needed for WBJEE 2026 admission?"*, the system detects the topic switch and triggers fresh retrieval.

---

### 3. Dual-Path Hybrid Retrieval Engine (`retrieve.py`)

The retrieval router `retrieve_context(question, top_k)` directs queries through specialized retrieval pipelines:

#### A. Temporal Retrieval (`retrieve_time_based`)
- Directly queries MongoDB `university_documents` for notices with `status: "processed"`.
- Parses official notice dates (`issue_date` in formats `%d-%m-%Y` and `%d-%m-%Y %H:%M`), falling back to `detected_at`.
- Evaluates calendar dates using official university timezone (`Asia/Kolkata`).
- Supports exact calendar filtering for **Today** and **Yesterday**, as well as reverse-chronological sorting for **Latest** notices.

#### B. Semantic Vector Retrieval with Metadata & Lexical Reranking (`retrieve_semantic`)
1. **Year Extraction & Metadata Filtering:**
   - Extracts 4-digit years from the query (e.g., `2025`, `2026`).
   - Queries Pinecone serverless index `uniai` (namespace `notices`) with metadata filter `{"year": {"$eq": year}}`.
   - **Filter Recovery:** If zero hits are returned with the filter, automatically retries without the filter and verifies year against document content (`_document_year_matches`).
2. **MongoDB Batch Document Hydration:**
   - Performs a single `$in` batch query on MongoDB for all vector hit IDs, replacing inefficient $N+1$ single-record lookups.
3. **Lexical Reranking (`_lexical_score`):**
   - Computes keyword overlap between query tokens and notice title/body/key points.
   - Blends dense similarity with sparse lexical ranks using Reciprocal Rank Fusion (RRF).
4. **Admission Round & Subject Scoping:**
   - Prevents document confusion by scoping queries to specific rounds (e.g., 1st round vs 2nd round) and exams (WBJEE vs JECA vs JELET).

---

### 4. Anti-Hallucination Evidence Grounding (`evidence.py` & `prompt.py`)

The evidence verification pipeline guarantees responses are 100% grounded in official records:

1. **Evidence Bundle Construction (`build_evidence_bundle`):**
   - Compiles structured fields into labeled atomic facts (`[N1-E1]`, `[N1-E2]`, etc.).
2. **Strict Generation Prompt (`prompt.py`):**
   - Enforces that each generated claim must reference exactly one `notice_id` and include valid `evidence_refs`.
3. **Server-Side Claim Validation (`validate_claims`):**
   - Independent Python validator checks model outputs against server-side truth.
   - **Number Verification:** Ensures all numbers in the claim exist in the cited evidence.
   - **Month & Date Verification:** Rejects claims that change date months or swap deadlines.
   - **URL Verification:** Only URLs explicitly appearing in official notice text or metadata can be cited.
4. **Academic Eligibility Safeguard (`_apply_eligibility_guard`):**
   - When circulars mandate both Physics AND Mathematics as compulsory subjects, the validator rejects answers that misstate them as optional alternatives (*"Physics, Mathematics, or other subjects"*).
5. **Cautious Missing-Value Guidance (`missing_amount_guidance`):**
   - When a student asks about a fee or placement package not stated in the circular, UniAI delivers data-grounded guidance without hallucinating numeric figures or assuming negative facts.
6. **Sequential Notice List Formatting (`format_notice_list` & `format_notice_line`):**
   - For multi-notice search results and chronological listings (e.g., *"give 5 recent notices"*), formats each record sequentially starting from 1 (`1.`, `2.`, `3.`, `4.`, `5.`).
   - Includes headline, official issue date, university reference number, complete non-truncated summary, and direct official PDF source URL.
   - Designed to work seamlessly with frontend markdown rendering so each numbered notice block maintains its explicit serial order without resetting to 1.

---

## 📂 Source Code Files

| File | Description |
|---|---|
| [`main.py`](main.py) | **Main Assistant Orchestrator & CLI:** Integrates state management, query understanding, retrieval, RAG chain invocation, response formatting, and citation tracking. |
| [`retrieve.py`](../retrieve.py) | **Hybrid Retrieval Engine:** Pinecone semantic search, year filtering, batch document hydration, lexical reranker (RRF), and temporal retrieval. |
| [`query_understanding.py`](query_understanding.py) | **Query Understanding Layer:** Pydantic schema for 9 query intents, intent parser, topic switch detector, and fallback heuristics. |
| [`conversation_state.py`](conversation_state.py) | **Session Memory & State:** Multi-turn chat history, active notice tracking, cited records management, and student name memorization/correction. |
| [`evidence.py`](evidence.py) | **Evidence Grounding Engine:** Fact bundling, server-side claim validation, eligibility safeguards, and source formatting. |
| [`prompt.py`](prompt.py) | **Prompt Engineering:** Strict anti-hallucination LangChain prompt template enforcing atomic claims and verified citations. |
| [`README.md`](README.md) | Module 4 technical documentation and operational guide. |

---

## ⚙️ Environment Configuration

Set the following variables in your root `.env` file:

```env
# Database & Vector Index
MONGO_URI=mongodb+srv://<username>:<password>@cluster0.mongodb.net/?retryWrites=true&w=majority
PINECONE_API_KEY=pcsk_...

# LLM Provider: "groq" (default cloud) or "ollama" (local)
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile

# If using local Ollama:
# LLM_PROVIDER=ollama
# OLLAMA_MODEL=qwen3:4b-instruct
# OLLAMA_KEEP_ALIVE=30m

# Diagnostics (Optional)
UNIAI_DEBUG=0
```

---

## ▶️ How to Run

### 1. Interactive Assistant (CLI)

From the project root:
```bash
python3 backend/Module4/main.py
```

From the module directory:
```bash
cd backend/Module4
python3 main.py
```

### 2. Debug Mode

To inspect intent parsing, Pinecone hit scores, lexical reranking, and evidence validation in real-time:

```bash
UNIAI_DEBUG=1 python3 backend/Module4/main.py
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

UniAI: The Hostel Seat Application notice requires students to submit the Google Form by 16 October 2026 [Source: https://makautwb.ac.in/datas/users/0-googlfrom26.pdf]. The Hostel Closure Notice requires all boarders to vacate their rooms by 14 October 2026 [Source: https://makautwb.ac.in/datas/users/0-notice_holiday26.pdf].

You: Which of these two hostel deadlines comes first, and by how many days?

UniAI: The Hostel Closure Notice deadline comes first on 14 October 2026, while the Hostel Seat Application deadline is on 16 October 2026. The difference is 2 days.
```

---

## ✅ Quality & Robustness Highlights

- [x] **Zero Hallucination:** Strict prompt instructions and server-side claim validation prevent fabricated answers.
- [x] **Dual Retrieval Paths:** Distinguishes temporal queries (latest/today/yesterday) from semantic topic queries.
- [x] **Resilient Year Filtering:** Automatic recovery without Pinecone metadata filters ensures notices are never dropped due to schema mismatches.
- [x] **Lexical Reranker (RRF):** Token overlap scoring prevents document confusion (e.g., distinguishing admission verification from registration closure).
- [x] **Active Notice Continuity:** Contextual follow-up queries do not re-run full vector searches when the active notice is already in session.
- [x] **Topic Switch Detection:** Automatically detects when a student shifts to a new topic or academic year, preventing stale context contamination.
- [x] **Exact Citation Tracking:** Preserves only the notices cited in assistant answers for subsequent multi-document comparisons.
- [x] **Verified Official Links:** Every factual answer cites the official university PDF URL.
