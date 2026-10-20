# 🛠️ Module 4 — Engineering Changelog & Reliability Hardening

> **University AI Assistant (UniAI) — MAKAUT**  
> Technical record of algorithmic fixes, query classification hardening, dual-path retrieval optimizations, and evidence validation safeguards.

---

## 📌 Overview of Enhancements

This document records the architectural improvements, bug fixes, and reliability hardening applied to **Module 4** to eliminate hallucinations, prevent query routing misclassifications, and ensure deterministic multi-turn conversational performance.

---

## 🔧 Key Improvements by Component

### 1. Assistant Orchestrator (`main.py`)
- **Topical Routing Safeguard:** Topic queries are only routed to chronological "newest-notice" retrieval when the user's specific wording or classified intent explicitly requests the newest/latest notice, preventing general subject searches from arbitrarily returning single recent circulars.
- **Candidate Pool Expansion:** Semantic topic queries now fetch a generous candidate pool (15–40 documents from Pinecone and MongoDB) before applying RRF ranking and candidate scoping. Only the top 5 highest-ranking verified documents are passed to the LLM context.
- **Complete Sentence Truncation:** Summary formatters enforce clean sentence boundaries (avoiding cutting off text mid-word with ellipses).
- **Comparison Output Recovery:** If an LLM response fails validation or omits one of the compared notices in a comparison query, an automated single-retry repair loop with explicit instructions re-prompts the model for independent atomic claims before returning.
- **Single-Notice Overview Completeness:** Automatically validates that admission notices cover key facets (programs, eligibility, deadlines, reporting) when supported by evidence.
- **`NO_RESULTS_MESSAGE` Fallback:** Centralized graceful fallback message returned whenever facts are absent or unverified:
  > *"I could not find this information in the available university notices."*

---

### 2. Hybrid Retrieval Engine (`retrieve.py`)
- **Year-Filtered Vector Retrieval with Broad Fallback:** Queries Pinecone with metadata filter `{"year": {"$eq": year}}`. If zero or insufficient records are returned (e.g., due to schema variations in older indexed notices), automatically executes a broad vector search and validates document content against the requested year.
- **Single Batch MongoDB Fetch:** Replaced the legacy $N+1$ loop (`find_one` per Pinecone vector hit) with a single atomic `$in` query across all returned vector IDs, cutting retrieval latency dramatically.
- **Reciprocal Rank Fusion (RRF) & Lexical Reranker:** Dense vector similarity ranks and sparse BM25-style token overlap scores are merged using RRF (`1 / (60 + rank)`), with domain bonuses for official admission rounds and exact issue dates.
- **Legacy MongoDB Regex Fallback:** Performs a targeted title and summary regex scan on MongoDB for notices published prior to vector indexing, ensuring older circulars are never lost.
- **Timezone-Aware Calendar Parsing:** Queries specifying "today" or "yesterday" are parsed relative to the official university timezone (`Asia/Kolkata`).

---

### 3. Query Understanding Layer (`query_understanding.py`)
- **Conversational Correction Priority:** High-priority deterministic pattern matching recognizes user identity declarations and conversational corrections (e.g., *"Actually, correct my name to Farhan"*), classifying them as `casual_chat` instead of triggering a notice search for student certificate correction circulars.
- **Topic Switch Detector (`explicitly_changes_notice_topic`):** Compares explicit exam markers (WBJEE, JECA, JELET, CET, Hostel, Registration) and academic years between the user's new message and the active notice. When a new entity is introduced, the system resets active notice focus and forces a fresh vector retrieval.
- **Selective Follow-up Routing:** Fallback heuristics no longer treat every question mentioning a field (e.g., "fee" or "deadline") as a follow-up; only queries with demonstrative pronouns (*"this notice"*, *"that notice"*) or short follow-up phrases retain active notice context.
- **Singular Query Count Normalization:** When a student asks about a specific notice (e.g., *"WBJEE 2026 notice"*), the target count is strictly normalized to `1`, preventing 4-digit years from being misread as record count limits.

---

### 4. Evidence Grounding & Anti-Hallucination (`evidence.py`)
- **Atomic Server-Side Reference Catalog:** Structured notice fields are flattened into numbered references (`[N1-E1]`, `[N1-E2]`). The claim validator checks text against server-side truth rather than model-generated quotations.
- **Strict Lexical & Numeric Validation:**
  - **Numbers & Dates:** Rejects any claim containing numbers, percentages, or months absent from the cited evidence.
  - **Currencies & Fees:** Disallows claims containing unverified currencies (`INR`, `USD`).
  - **URLs:** Ensures cited URLs exist in official notice text or metadata.
- **Compulsory Subject Guard (`_apply_eligibility_guard`):** Explicitly verifies that circulars requiring mandatory Physics AND Mathematics are not rewritten with optional language (*"Physics, Mathematics, or other subjects"*).
- **Cautious Missing-Value Guidance (`missing_amount_guidance`):** Returns data-grounded guidance for unstated fees or placement figures without hallucinating numbers or negative assertions.

---

## 🏃 Running with Diagnostic Logging

To inspect query classification, Pinecone scores, lexical reranking, and claim validation in real-time:

```bash
UNIAI_DEBUG=1 python3 backend/Module4/main.py
```
