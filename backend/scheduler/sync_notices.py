"""Phase 5: one-shot ingestion job for GitHub Actions, NOT a background web server.

Run: python backend/scheduler/sync_notices.py
Exit 1 when the current batch has a processing/indexing error, so GitHub alerts.
"""
import json
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
# Module2's existing imports are "from ocr import ..." / "from prompt import ...".
# Put Module2 on sys.path without altering the user's OCR/prompt/schema code.
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR / "Module2"))


def _limit(name, default):
    value = int(os.getenv(name, str(default)))
    if value < 0 or value > 100:
        raise ValueError(f"{name} must be between 0 and 100")
    return value


def run_sync(scrape_fn=None, process_fn=None, index_fn=None, recheck_fn=None):
    """Dependency-injected for network-free regression tests."""
    if scrape_fn is None or recheck_fn is None:
        from Module1.scrapper import run_monitor_cycle, recheck_existing_pdf_versions
        scrape_fn = scrape_fn or run_monitor_cycle
        recheck_fn = recheck_fn or recheck_existing_pdf_versions
    if process_fn is None:
        from Module2.main import process_new_notices
        process_fn = process_new_notices
    if index_fn is None:
        from Module3.main import index_all_processed_notices
        index_fn = index_all_processed_notices

    print("[Phase5] Starting MAKAUT notice synchronization", flush=True)
    discovery = scrape_fn()
    if not isinstance(discovery, dict):
        raise TypeError("Module1 must return a discovery report")

    revision_report = recheck_fn(limit=_limit("SYNC_RECHECK_EXISTING", 2))
    extraction = process_fn(limit=_limit("SYNC_PROCESS_LIMIT", 3))
    if not isinstance(extraction, dict):
        raise TypeError("Module2 must return a processing report")

    indexed, index_failed = index_fn(limit=_limit("SYNC_INDEX_LIMIT", 10))
    report = {
        "discovery": discovery,
        "revisions": revision_report,
        "extraction": extraction,
        "indexed": indexed,
        "index_failed": index_failed,
    }
    print("[Phase5] SUMMARY=" + json.dumps(report, default=str, sort_keys=True), flush=True)

    if extraction.get("failed", 0) or index_failed:
        raise RuntimeError("One or more notice processing/indexing operations failed; see job logs")
    return report


def main():
    try:
        run_sync()
        return 0
    except Exception as exc:
        print(f"[Phase5] Sync run FAILED: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
