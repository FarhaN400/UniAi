# UniAI — Final 50-question evaluation

This folder contains the 50-question evaluation promised after fixing the
original 12 issues. The questions cover nine categories: retrieval (8),
recent/dated notices (6), deadlines/academic sessions (6), fee/eligibility
(6), required documents (6), six-turn follow-ups (6), comparison (4),
missing information (4), and out-of-scope requests (4).

## What's ready

- `questions_50.json`: 50 distinct prompts, grouped by topic, with the
  behavior that reviewers should check.
- `run_50.py`: **opt-in** real `POST /api/chat` evaluation. One conversation
  is reused across the six follow-up questions; all other questions start
  fresh. Uses unique request IDs. It records HTTP status, duration,
  responses, PDF sources and whether URLs use MAKAUT's official HTTPS domain.
- `results_50.csv`: produced locally when you run the command (not stored
  in GitHub).

## Run AFTER PR #6 is merged and the backend is deployed

```bash
python backend/evaluation/run_50.py \
  --base-url https://YOUR-DEPLOYED-FASTAPI-HOST \
  --run-live \
  --out backend/evaluation/results_50.csv
```

This makes **50 actual backend calls**, consuming AI and Pinecone quota; don't
run it as a GitHub CI gate. It requires a reachable backend, processed real
MAKAUT notices and MongoDB persistence for multi-turn testing. If your backend
is private, run from a machine allowed to access it.

## How to grade

The script **does not automatically claim 50/50 correctness**. URL validity
and response collection alone cannot prove that a required document, fee, date
or qualification actually appears in the correct official notice. For each
row, compare the answer and source against the original official PDF.

Change `manual_verdict` from `not_reviewed` to `pass` or `fail`, and write
the actual issue in `reviewer_notes`. Retest every failed case after it is
corrected, including the whole six-question conversation flow.

A missing or discontinued real notice is not grounds for manufacturing an
expected answer. A safe "no matching processed notice" answer may be
correct if the exact source is not present.

The test set is ready, but **live 50-question execution has not been
performed** as part of this PR, because a reachable deployed API and the
actual notices must be verified after merging.
