# UniAI Module 4 — patched files

Replace the five corresponding files in your existing Module 4 directory. Keep your existing `.env`, database, index, and model setup.

## Run

```bash
export UNIAI_DEBUG=1
python main.py
```

Try:

1. `What documents are required for WBJEE 2025 document verification?`
2. `What are the document verification requirements mentioned in the WBJEEB-2025 first-round admission notice?`
3. `What documents do students need to bring for admission verification at MAKAUT?`
4. `What is the latest notification published by MAKAUT?`

## Changes

- `main.py`: only routes topic queries to newest-notice retrieval when the wording/intent calls for newest, not merely when `count=1`. Semantic queries fetch 12+ candidate records and pass a maximum of five to Qwen. Summary formatting ends on a complete sentence where possible. Logs query classification under `UNIAI_DEBUG=1`.
- `retrieve.py`: tries Pinecone year filter, retries without filter when needed, rejects year-mismatching documents, ranks candidate notices using question/title/body token overlap and Pinecone similarity, and uses a limited MongoDB year fallback for old notices missing from Pinecone. Logs Pinecone hits and lookup failures.
- `query_understanding.py`: fallback parsing no longer treats every question mentioning a field as a follow-up.
- `prompt.py` and `conversation_state.py`: retained from uploaded code.

## Limitations

- No live Pinecone, MongoDB, or Ollama environment was provided here; only static code validation was possible.
- Best results still require documents to have useful `structured_data`, particularly document requirement details.
- Year detection searches record title, summary, key points, academic year and URL. A relevant legacy record with none of those fields containing the year may remain unavailable.
- Results depend on the Pinecone index schema and SDK version already used in your project.
