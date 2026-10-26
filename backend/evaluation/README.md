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

## Verify the Render revision before evaluating

The Render **/health** endpoint reports the public source commit in `revision`
(from Render's built-in `RENDER_GIT_COMMIT`). This prevents an old deployment
from masquerading as a failed fix. Merge the patch, update your working copy,
then confirm the running backend revision before making any billable requests.

```bash
/usr/bin/git pull --ff-only origin main
REV=$(/usr/bin/git rev-parse --short=12 HEAD)
curl -fsS https://uniai-backend-1isk.onrender.com/health
```

The `revision` field must begin with `$REV`. If it does not, inspect
the active commit under **Render > your backend > Deploys**. A 200 health
response alone does not verify which GitHub commit was deployed.

First run only the four previously incorrect-source questions:

```bash
python3 backend/evaluation/run_50.py \
  --base-url https://uniai-backend-1isk.onrender.com \
  --expect-revision "$REV" \
  --only Q03 Q17 Q23 Q24 \
  --run-live \
  --out backend/evaluation/results_4_release_smoke.csv
```

Inspect the CSV for unrelated notice sources. Specifically: Q03 must not
cite anti-ragging/refund notices, Q17/Q24 must not cite generic lateral
registration as a JELET-specific notice, and Q23 must not cite a hostel
allotment notice. Incomplete results must clearly report what is unknown
rather than inventing requirements.

## Run the full evaluation AFTER deployment verification

```bash
python backend/evaluation/run_50.py \
  --base-url https://YOUR-DEPLOYED-FASTAPI-HOST \
  --expect-revision "$REV" \
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

CI runs synthetic unit tests without network/model quota. The full live
evaluation must be initiated intentionally after deployment, then reviewed
against the original university PDFs. A 50/50 HTTP success rate does not
establish factual accuracy.
