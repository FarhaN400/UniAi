# Backfill v2 adds --skip to bypass known unmatched documents while leaving
# their status and metadata unchanged. The skip offset is relative to the
# current list of processed notices without a PDF hash; revisit it after a run.
"""Phase 5: establish SHA-256 baselines for already-processed MAKAUT PDFs.

Run from the UniAI/backend directory:
    python3 -m scheduler.backfill_pdf_hashes --limit 10
    python3 -m scheduler.backfill_pdf_hashes --limit 10 --apply
    python3 -m scheduler.backfill_pdf_hashes --skip 6 --limit 10

Default is read-only. --apply saves a hash only when current PDF text exactly
matches the notice's stored raw_text (using direct extraction or Tesseract OCR).
This script never calls Groq or Pinecone and never alters structured_data.
"""

import argparse
import hashlib
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests
from dotenv import find_dotenv, load_dotenv
from pymongo import MongoClient
from Module2.ocr import extract_pdf_text, ocr_extract_pdf

MAX_PDF_BYTES = 25 * 1024 * 1024
ALLOWED_HOSTS = {"makautwb.ac.in", "www.makautwb.ac.in"}


def download_pdf(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS:
        raise ValueError("Unexpected PDF source URL")

    with requests.get(url, timeout=(10, 40), stream=True) as response:
        response.raise_for_status()
        final = urlsplit(response.url)
        if final.scheme != "https" or final.hostname not in ALLOWED_HOSTS:
            raise ValueError("PDF redirected to an unapproved host")

        chunks = []
        total = 0
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_PDF_BYTES:
                raise ValueError("PDF exceeds the 25 MiB size limit")
            chunks.append(chunk)

    payload = b"".join(chunks)
    if not payload.startswith(b"%PDF-"):
        raise ValueError("Downloaded content is not a PDF")
    return payload


def pdf_matches_saved_text(pdf_bytes, saved_text):
    with tempfile.NamedTemporaryFile(suffix=".pdf") as pdf_file:
        pdf_file.write(pdf_bytes)
        pdf_file.flush()

        if extract_pdf_text(pdf_file.name).strip() == saved_text:
            return "Direct/automatic extraction"
        if ocr_extract_pdf(pdf_file.name).strip() == saved_text:
            return "Tesseract OCR"
    return None


def run(limit, apply, skip=0):
    load_dotenv(find_dotenv(usecwd=True))
    mongo_uri = os.getenv("MONGO_URI")
    if not mongo_uri:
        raise RuntimeError("MONGO_URI missing from environment")

    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=10000)
    stats = {"checked": 0, "matched": 0, "saved": 0, "review": 0, "errors": 0}
    try:
        collection = client["university_assistant"]["university_documents"]
        cursor = collection.find({
            "status": "processed",
            "pdf_sha256": {"$exists": False},
        }).sort("_id", -1).skip(skip).limit(limit)

        print("--- PHASE 5 PDF HASH BACKFILL ---")
        print("Mode:", "APPLY" if apply else "DRY RUN (no writes)")
        print("Skip first unresolved notices:", skip)

        for notice in cursor:
            stats["checked"] += 1
            title = notice.get("title") or "Untitled notice"
            print(f"\n[{stats['checked']}/{limit}] {title}")
            try:
                saved_text = (notice.get("raw_text") or "").strip()
                if not saved_text:
                    stats["review"] += 1
                    print("REVIEW: No stored raw_text")
                    continue

                pdf_bytes = download_pdf(notice.get("url", ""))
                method = pdf_matches_saved_text(pdf_bytes, saved_text)
                if method is None:
                    stats["review"] += 1
                    print("REVIEW: Neither extraction method matches stored text")
                    continue

                stats["matched"] += 1
                digest = hashlib.sha256(pdf_bytes).hexdigest()
                print(f"MATCH: {method}; SHA256: {digest}")

                if not apply:
                    print("DRY RUN: Hash not saved")
                    continue

                # Atomic guard: don't overwrite another run's metadata or
                # a notice whose content/status changed while downloading.
                result = collection.update_one({
                    "_id": notice["_id"],
                    "status": "processed",
                    "raw_text": notice["raw_text"],
                    "pdf_sha256": {"$exists": False},
                }, {"$set": {
                    "pdf_sha256": digest,
                    "pdf_hash_checked_at": datetime.now(timezone.utc),
                }})
                if result.modified_count == 1:
                    stats["saved"] += 1
                    print("SAVED: Baseline hash stored in MongoDB")
                else:
                    stats["review"] += 1
                    print("SKIPPED: Record changed or hash already written")
            except Exception as exc:
                stats["errors"] += 1
                print(f"ERROR: {type(exc).__name__}: {exc}")

        print("\n--- SUMMARY ---")
        for key, count in stats.items():
            print(f"{key}: {count}")
        print("MongoDB writes:", stats["saved"])
        print("Groq calls: 0; Pinecone writes: 0")
        return stats
    finally:
        client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=10, help="Number of notices (1–25)")
    parser.add_argument("--skip", type=int, default=0, help="Skip the first N remaining notices (default 0)")
    parser.add_argument("--apply", action="store_true", help="Save verified hashes")
    args = parser.parse_args()
    if not 1 <= args.limit <= 25:
        parser.error("--limit must be between 1 and 25")
    if args.skip < 0:
        parser.error("--skip must be 0 or greater")
    run(args.limit, args.apply, args.skip)


if __name__ == "__main__":
    main()
