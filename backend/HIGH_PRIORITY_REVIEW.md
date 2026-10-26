# UniAI high-priority reliability fixes (#5–#8)

This branch groups four independent fixes into **one pull request**. Merge once
after reviewing and checking the tests. The earlier fixes #1–#4 are already
part of `main`.

## #5 — Missing evidence

When the RAG model cannot verify the requested fact, the answer remains
"I could not find this information in the available university notices."
The backend **does not replace it** with a general notice overview or unrelated
PDF. When the model or provider fails, the answer explicitly says the service
is unavailable and records **no supporting source**.

## #6 — Previous answer's sources appearing on a new answer

The source sidebar is scoped to the most recent assistant turn, including
turns with zero citations. Clicking **N official notice source(s)** on an
older answer opens citations for **that answer only**. New answers and chat
switches reset the previous source selection.

## #7 — Issue date vs detection date

`notice_dates.official_issue_date()` parses only the date extracted from
the notice. `detected_at` remains an internal fallback for *sorting*, not
for date-specific factual claims. Today/yesterday, "issued on", "published in
YYYY" and explicitly dated semantic retrieval require actual official dates.
Supported formats include DD-MM-YYYY, DD/MM/YYYY, DD.MM.YYYY, ISO, and
English month names; invalid/missing dates are not treated as publication
dates.

## #8 — Long-PDF review queue

Long documents continue to be quarantined for human review by default. This
is intentional: publishing conflicting OCR without checks would cause
hallucinations. Previously there was no explicit workflow to clear the queue.

### Review steps

You must have access to the `MONGO_URI` environment variable in the secure
backend execution environment, with `pymongo` and `python-dotenv`
installed. **Do not put MongoDB credentials in the frontend or GitHub source.**

From the repository root:

```bash
python backend/scheduler/review_notices.py list
python backend/scheduler/review_notices.py show YOUR_NOTICE_ID
```

Open the actual university PDF shown in the record and compare it to
`structured_data`, `raw_text`, `chunk_extractions`, dates, fees, and
document requirements. **Only after this human comparison**, approve:

```bash
python backend/scheduler/review_notices.py approve YOUR_NOTICE_ID \
  --reviewer "Your reviewer name" \
  --notes "Verified all document facts against original university PDF"
```

When the merged extraction includes explicit `requiring verification`
warnings, approval is blocked unless a reviewer documents their decision and
adds `--acknowledge-warnings`. This cannot override missing raw PDF text or
title data.

To reject an unusable extraction:

```bash
python backend/scheduler/review_notices.py reject YOUR_NOTICE_ID \
  --reviewer "Your reviewer name" \
  --notes "Official PDF is inconsistent with OCR extraction"
```

An approved record changes to `status=processed`, with
`quality_review_required=false` and `pinecone_indexed=false`.
The Module3 indexer **then** picks it up on the next successful scheduled
sync. To index immediately in an environment with MongoDB and Pinecone
configured:

```bash
cd backend/Module3
python main.py
```

The approval records a timestamp, reviewer, notes, and acknowledged warnings.
The CLI uses an atomic update so it cannot approve an already changed PDF.
Review/rejection is deliberately an explicit manual operation; existing
`review_required` PDFs are **not automatically made searchable by deployment
alone**.

## Offline verification

```bash
PYTHONPATH=backend python -m unittest discover \
  -s backend/tests -p 'test_high_priority_batch.py' -v

cd frontend
npm ci
node --test tests/sources.test.mjs
npm run build
```

The branch's GitHub Actions workflow runs those tests without requiring live
cloud credentials. The planned **50-question live chatbot evaluation** follows
the remaining lower-priority fixes, not this isolated batch.
