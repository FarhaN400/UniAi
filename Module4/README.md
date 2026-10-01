# 🤖 Module 4 — Student Query Processing, Hybrid Retrieval & RAG Pipeline

> **University AI Assistant — MAKAUT**  
> Conversational question answering system connecting natural language student queries to official university notices via multi-strategy retrieval and grounded LLM generation.

Module 4 represents the reasoning and user-facing intelligence layer of **UniAI**. It takes questions asked by students in natural language, analyzes their intent, retrieves official university notices through a hybrid routing system (Pinecone semantic search + MongoDB temporal queries), maintains multi-turn conversational context, and prompts a large language model to produce accurate, hallucination-free answers with verifiable official notice links.

---

## 🎯 Objective

1. **Natural Language Understanding:** Allow students to query complex university procedures, dates, fees, and rules conversationally (e.g. *"What documents do I need for WBJEE 2026 admission?"* or *"Give me 4 latest notices"*).
2. **Hybrid Retrieval Routing:**
   - **Semantic Path:** Pinecone vector search over rich notice embeddings with metadata filtering on academic year.
   - **Temporal Path:** MongoDB date-sorted retrieval for time-sensitive questions (*"today"*, *"yesterday"*, *"latest notices"*).
   - **Topic Path:** Targeted regex search across official titles, raw OCR text, and key points for domain topics (e.g., WBJEE).
3. **Conversational Memory & Follow-ups:** Resolve conversational references such as *"tell me more about this notice"*, *"now the 5th one"*, or *"give only one notice"*.
4. **Anti-Hallucination Grounding:** Enforce strict grounding rules so that the LLM only answers from official notice data, cleanly citing the document title and source PDF URL.

---

## 🏗️ Architecture & Query Flow

```text
                           Student Query
                                 │
                                 ▼
                     Intent & Parameter Parsing
            ┌────────────────────┼────────────────────┐
            ▼                    ▼                    ▼
     Time-Based Query     Specific Topic       Informational
   ("latest", "today",   ("wbjee", "jelet")     (General QA)
      "yesterday")               │                    │
            │                    ▼                    ▼
            │           Topic Search         Year Extraction
            │           (MongoDB Regex)      (e.g., 2026 / 2025)
            │                    │                    │
            ▼                    │                    ▼
     MongoDB Retrieval           │           Pinecone Semantic
     (Sorted by official         │           Search (`uniai`)
        issue_date)              │           - Namespace: "notices"
            │                    │           - Metadata Filter: year
            └────────────────────┼────────────────────┘
                                 │
                                 ▼
                      Notice Hydration (MongoDB)
                     (Fetch full structured JSON)
                                 │
                                 ▼
                    Follow-up & Ordinal Router
              - Ordinal selection ("5th one")
              - Single-notice filter ("just 1")
              - Formatted lists for multi-notice queries
                                 │
                                 ▼
                     Grounded Context Assembly
             (Title, Type, Summary, Dates, Source URL)
                                 │
                                 ▼
                   LangChain RAG Chain Execution
                 (Prompt + Chat History + Context)
                                 │
                                 ▼
                LLM: Hugging Face (gpt-oss-120b)
                                 │
                                 ▼
                    Final Grounded Answer
                + Official MAKAUT PDF Link
```

---

## 🔍 Retrieval Strategies & Routing

Module 4 utilizes an intelligent dispatcher in [`retrieve.py`](file:///Users/farhanakhtar/Desktop/Project/UniAi/Module4/retrieve.py):

### 1. Semantic Vector Retrieval (`retrieve_semantic`)
- Queries the Pinecone serverless index (`uniai`, namespace `notices`).
- **Year-Aware Filtering:** Automatically extracts 4-digit years from the question via `extract_year_from_question(question)`:
  ```python
  if year:
      query_params["filter"] = {"year": {"$eq": year}}
  ```
  This guarantees that questions about *"WBJEE 2026"* never accidentally retrieve circulars from 2024 or 2025.
- Hits return `notice_id` values, which are then hydrated from MongoDB to access the complete structured JSON and source URLs.

### 2. Temporal Retrieval (`retrieve_time_based`)
- Activated when keywords like `"latest"`, `"recent"`, `"today"`, or `"yesterday"` are detected.
- Parses official notice dates (`issue_date` formatted as `DD-MM-YYYY`), falling back to `detected_at`.
- Performs precise calendar date filtering for *"today"* / *"yesterday"* or returns the latest $K$ notices sorted in descending chronological order.

### 3. Topic-Specific Retrieval (`retrieve_topic_notices`)
- Detects specialized keywords (e.g. `wbjee`, `wbjeeb`).
- Performs regex lookups against structured titles, scraped titles, raw OCR text, and bullet key points.

---

## 💬 Conversational Memory & Follow-up Resolution

The main orchestrator in [`main.py`](file:///Users/farhanakhtar/Desktop/Project/UniAi/Module4/main.py) maintains session state (`chat_history`, `last_latest_question`, `last_notice_records`):

| Follow-up Pattern | Example Query | Handling Logic |
|---|---|---|
| **Requested Count** | *"Give me 6 latest notices"* | `extract_requested_count` parses digits and words (1–10) and fetches the exact count. |
| **Ordinal Selection** | *"Now the 5th one"* or *"show me the third"* | `extract_notice_ordinal` isolates the 5th notice from the previous latest-notices result set. |
| **Single Notice Request** | *"give only one notice"* / *"just 1"* | `is_single_notice_follow_up` renders only the primary notice without re-running full retrieval. |
| **Detail Expansion** | *"tell me more about this notice"* | `is_notice_detail_follow_up` invokes the LLM using the previously referenced notice as exclusive context. |

---

## 🛡️ Anti-Hallucination RAG Prompt

The prompt template defined in [`prompt.py`](file:///Users/farhanakhtar/Desktop/Project/UniAi/Module4/prompt.py) enforces strict university information standards:

```python
rag_prompt = ChatPromptTemplate.from_template("""
You are UniAI, an AI assistant helping students understand official university notices.

You must answer using ONLY the information in the retrieved context.
Do not use outside knowledge, assumptions, or common sense.

IMPORTANT RULES:
1. Use only the official information present in the provided context.
2. Do not invent dates, deadlines, fees, documents, eligibility rules, or procedures.
3. If the context does not contain the requested answer, respond exactly:
   "I could not find this information in the available university notices."
4. Preserve official details exactly as given, including dates, names, fees, and deadlines.
5. If a Source URL is included in the context, add it at the end of the answer so the student can verify the official notice.
6. Do not mention internal system details such as Pinecone, MongoDB, vector search, retrieval, RAG, JSON, or backend implementation.
7. For multiple notices, do not use a table. Put each notice on one concise line:
   **Headline** | Date: ... | Key detail: ... | Source: ...
...
""")
```

---

## 📂 Core Files Overview

| File | Description |
|---|---|
| [`main.py`](file:///Users/farhanakhtar/Desktop/Project/UniAi/Module4/main.py) | **Main Assistant & RAG Orchestrator:** LangChain Hugging Face model (`openai/gpt-oss-120b`), query classification, ordinal resolution, conversational memory, and interactive CLI. |
| [`retrieve.py`](file:///Users/farhanakhtar/Desktop/Project/UniAi/Module4/retrieve.py) | **Retrieval Engine:** Pinecone semantic search, MongoDB temporal & topic retrieval, year extraction, document hydration, and context compilation. |
| [`prompt.py`](file:///Users/farhanakhtar/Desktop/Project/UniAi/Module4/prompt.py) | **Prompt Engineering:** Strict anti-hallucination LangChain prompt template enforcing official citations and concise outputs. |
| [`test.py`](file:///Users/farhanakhtar/Desktop/Project/UniAi/Module4/test.py) | **Automated Test Suite:** Comprehensive test cases validating count requests, ordinal follow-ups, topic filters, year-based Pinecone filtering, and date queries. |

---

## ⚙️ Environment Variables

Module 4 requires credentials in the root `.env` file:

```env
MONGO_URI=mongodb+srv://...
PINECONE_API_KEY=pcsk_...
HUGGINGFACEHUB_API_TOKEN=hf_...
```

---

## ▶️ How to Run

### 1. Interactive Student Assistant (CLI)

```bash
cd /Users/farhanakhtar/Desktop/Project/UniAi/Module4
python3 main.py
```

**Example CLI Session:**

```text
🎓 UniAI — University AI Assistant
Type 'exit' to stop.

You: What documents do I need for WBJEE 2026 admission?

UniAI: For WBJEE 2026 admission reporting at MAKAUT, you must submit:
1. WBJEE 2026 Allotment Letter & Rank Card
2. Class 10 & Class 12 Admit Cards & Marksheets
3. Domicile Certificate and Category Certificate (if applicable)
4. Anti-ragging declarations and medical fitness certificate.

Source: Notification for reporting of candidates for admission through WBJEE-2026
URL: https://makautwb.ac.in/datas/users/0-wbjee_reporting_2026.pdf

You: Give me 3 latest notices

UniAI: 1. Notice Regarding Semester Examination Form Fill-up
Date: 15-09-2026
Summary: Students are required to submit their examination forms online before the deadline.
Official source: https://makautwb.ac.in/datas/users/0-exam_form.pdf

2. Notification for WBJEE Reporting
Date: 11-09-2026
Summary: Reporting schedule and document verification instructions for candidate reporting.
Official source: https://makautwb.ac.in/datas/users/0-wbjee_notice.pdf

3. Campus Discipline and Gate Regulations
Date: 07-09-2026
Summary: Directives prohibiting the obstruction of university entry and administrative offices.
Official source: https://makautwb.ac.in/datas/users/0-discipline.pdf
```

### 2. Run the Automated Test Suite

```bash
python3 test.py
```

Runs 7 automated tests verifying:
- Requested record counts (e.g. *"Give me 6 latest notice"* $\rightarrow$ exactly 6 records)
- Ordinal follow-ups (e.g. *"now the 5th one"*)
- Notice list blank-line separation
- Live WBJEE topic lookup and detail follow-up resolution
- Academic year filtering (2026 vs 2025)
- Time-based queries (*"What is the latest notice?"*)
- Semantic QA (*"When is phase 2 registration?"*, *"Is ragging prohibited at this university?"*)

---

## ✅ Validation Checklist

- [x] Natural language intent detection and count extraction.
- [x] Dual-path retrieval routing (Pinecone semantic search + MongoDB temporal sorting).
- [x] Metadata year filtering (`$eq: year`) prevents cross-year circular confusion.
- [x] MongoDB notice hydration injects rich structured JSON into prompt context.
- [x] Conversational context and multi-turn follow-up resolution (`"the 5th one"`, `"tell me more"`).
- [x] Strict anti-hallucination prompt prevents fabricating dates, fees, or documents.
- [x] Fallback message `"I could not find this information in the available university notices."` triggered when context is absent.
- [x] Every response includes verified official document title and source PDF URL.
- [x] Automated test suite in `test.py` passes all validation steps.
