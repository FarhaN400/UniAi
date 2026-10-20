# ⏰ Automated Notice Scheduler & Cloud Synchronization (Phase 5)

> **University AI Assistant (UniAI) — MAKAUT**  
> Serverless recurring ingestion pipeline: automated MAKAUT portal crawling, in-place PDF revision checks, OCR & Pydantic extraction, Pinecone vector upsert, and temporary MongoDB Atlas IP authorization.

The **UniAI Scheduler** is the automated synchronization engine that runs on a recurring schedule in **GitHub Actions** (or can be invoked manually). It guarantees that the UniAI knowledge base is continuously updated with newly published official MAKAUT circulars, schedules, and examination notices without requiring manual intervention or keeping an expensive 24/7 server running.

---

## 🎯 Key Objectives

1. **Fully Automated Notice Sync:** Runs on a cron schedule (`17 */3 * * *`, every 3 hours) and on-demand via `workflow_dispatch`.
2. **Dynamic MongoDB Atlas IP Authorization (`run_with_atlas_access.py`):** Automatically fetches the GitHub Actions runner's public IPv4 address, authenticates via MongoDB Atlas Administration API v2 OAuth, creates a temporary 60-minute access rule, verifies connectivity, executes the sync job, and immediately deletes the IP rule upon completion.
3. **Resilient SSL Intermediate Certificate Provisioning:** Resolves MAKAUT's server-side certificate misconfiguration by fetching GlobalSign's intermediate certificate, verifying its SHA-1 fingerprint (`431955E6E5DABE857F1336C02368E5495F143EED`), and appending it to Python's `REQUESTS_CA_BUNDLE`.
4. **End-to-End Pipeline Execution (`sync_notices.py`):** Coordinates discovery (Module 1), in-place PDF revision checking (Module 1), structured extraction via Groq (Module 2), and vector indexing (Module 3) in a single bounded batch.
5. **In-Place PDF Revision Monitoring:** Detects when an existing circular is updated on the university server without a URL change by comparing streaming SHA-256 checksums (`recheck_existing_pdf_versions`).
6. **Hard Failure Reporting:** If any extraction or vector indexing operation fails, the scheduler exits with code `1`, causing GitHub to send an immediate alert.

---

## 🏗️ Cloud Pipeline Workflow

```text
               GitHub Actions Cron (Every 3 Hours)
                                │
                                ▼
         Fetch Runner Public IPv4 (via api.ipify.org)
                                │
                                ▼
         Atlas Admin API OAuth 2.0 Authentication
         - POST /api/atlas/v2/groups/{project}/accessList
         - Authorize runner IP with 60m deleteAfterDate
                                │
                                ▼
         Verify MongoDB Connectivity (client.admin.ping)
                                │
                                ▼
         Configure Resilient MAKAUT SSL CA Bundle
         - Fetch GlobalSign intermediate cert
         - Verify SHA-1: 431955E6E5DABE857F1336C02368E5495F143EED
         - Export REQUESTS_CA_BUNDLE
                                │
                                ▼
         Execute sync_notices.py (Phase 5 Engine)
         ├── 1. Module 1: Crawl MAKAUT portal & upsert new notices
         ├── 2. Module 1: Recheck rotating sample of PDF hashes
         ├── 3. Module 2: Download PDF, OCR / direct text, extract via Groq
         └── 4. Module 3: Upsert structured text to Pinecone notices
                                │
                                ▼
         Cleanup Runner IP (finally:)
         - DELETE /api/atlas/v2/groups/{project}/accessList/{ip}
                                │
                                ▼
         Exit 0 on Success / Exit 1 on Error (GitHub Alert)
```

---

## 📂 Source Code Files

| File | Description |
|---|---|
| [`sync_notices.py`](sync_notices.py) | **Main Sync Engine:** Single-batch orchestrator that invokes Module 1 discovery, PDF revision check, Module 2 extraction, and Module 3 Pinecone indexing. |
| [`run_with_atlas_access.py`](run_with_atlas_access.py) | **Atlas Access Manager:** Discovers runner IPv4, creates temporary Atlas access rule with 60m expiry, runs `sync_notices.py`, and cleans up IP. |
| [`backfill_pdf_hashes.py`](backfill_pdf_hashes.py) | **Hash Backfill Utility:** Computes and saves SHA-256 PDF hashes for legacy processed records in MongoDB that lack `pdf_sha256`. |
| [`report_pdf_baselines.py`](report_pdf_baselines.py) | **Audit & Baseline Reporter:** Inspects notice PDFs, measures OCR quality, and exports CSV baseline reports to `backend/phase5_reports/`. |
| [`phase5_isolated_e2e_test.py`](phase5_isolated_e2e_test.py) | **Isolated E2E Pipeline Test:** Runs full scrape $\rightarrow$ extract $\rightarrow$ index cycle on an ephemeral staging database and namespace, deleting all test artifacts afterwards. |
| [`run_isolated_e2e_with_atlas_access.py`](run_isolated_e2e_with_atlas_access.py) | **E2E Test Wrapper:** Authorizes runner IP on Atlas, runs `phase5_isolated_e2e_test.py`, and cleans up. |
| [`README.md`](README.md) | Phase 5 technical documentation and operations guide. |

---

## ⚙️ GitHub Actions Configuration

The workflow is defined in [`.github/workflows/notice_sync.yml`](file:///.github/workflows/notice_sync.yml).

### Required GitHub Secrets & Variables

| Name | Type | Purpose |
|---|---|---|
| `MONGO_URI` | Secret | MongoDB Atlas connection string |
| `PINECONE_API_KEY` | Secret | Pinecone vector database API key |
| `GROQ_API_KEY` | Secret | Groq API key for cloud LLM extraction (`openai/gpt-oss-20b`) |
| `ATLAS_CLIENT_ID` | Secret | MongoDB Atlas Programmatic API Key (Public Key) |
| `ATLAS_CLIENT_SECRET` | Secret | MongoDB Atlas Programmatic API Key (Private Key) |
| `ATLAS_PROJECT_ID` | Variable | MongoDB Atlas Group / Project ID (24-hex string) |

### Environment Variables & Tunables

```yaml
env:
  LLM_PROVIDER: groq
  GROQ_MODEL: openai/gpt-oss-20b
  SYNC_PROCESS_LIMIT: "1"        # Bounded batch extraction per run
  SYNC_INDEX_LIMIT: "1"          # Bounded vector upsert per run
  SYNC_RECHECK_EXISTING: "0"      # Rotating in-place PDF checks
  SYNC_MAX_ATTEMPTS: "4"         # Exponential backoff retry cap
  AUTO_APPROVE_LONG_NOTICES: "0" # Long notice review gate
```

---

## ▶️ How to Run Locally

### 1. Run Direct Synchronization (When IP is already authorized)

```bash
python3 backend/scheduler/sync_notices.py
```

### 2. Run with Temporary Atlas IP Authorization

```bash
python3 backend/scheduler/run_with_atlas_access.py
```

### 3. Generate PDF Baseline Report

```bash
python3 backend/scheduler/report_pdf_baselines.py
```

### 4. Backfill PDF SHA-256 Checksums

```bash
python3 backend/scheduler/backfill_pdf_hashes.py
```

### 5. Run Isolated End-to-End Pipeline Verification

```bash
python3 backend/scheduler/phase5_isolated_e2e_test.py
```

---

## ✅ Validation Checklist

- [x] Scheduled cron execution configured in GitHub Actions (`17 */3 * * *`).
- [x] Runner public IPv4 discovered dynamically via `api.ipify.org`.
- [x] Temporary Atlas IP authorization created with 60-minute automatic expiry.
- [x] Runner IP reliably cleaned up in `finally:` block after execution.
- [x] Resilient MAKAUT SSL intermediate certificate chain prevents HTTPS handshake errors.
- [x] Bounded batch extraction limits prevent runaway cloud inference costs.
- [x] In-place PDF content revisions detected via streaming SHA-256 hashing.
- [x] Automated exit code 1 alerts administrators immediately if sync fails.
