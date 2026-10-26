"""Review long MAKAUT notices before releasing them into Pinecone search.

From repository root:
  python backend/scheduler/review_notices.py list
  python backend/scheduler/review_notices.py show NOTICE_ID
  python backend/scheduler/review_notices.py approve NOTICE_ID --reviewer "Full Name" --notes "Checked full official PDF against extracted text."
  python backend/scheduler/review_notices.py reject NOTICE_ID --reviewer "Full Name" --notes "The scanned PDF does not match extracted requirements."
  python backend/scheduler/review_notices.py approve NOTICE_ID --reviewer "Full Name" --notes "Reviewed disputed dates against original PDF." --acknowledge-warnings

Then run the indexer (or the next notice-sync workflow) to index approved records.
No OCR/PDF is downloaded or modified by this CLI.
"""
import argparse
import json
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from review_workflow import approval_update, rejection_update, review_warnings


def _db():
    from dotenv import load_dotenv
    from pymongo import MongoClient
    load_dotenv()
    uri = os.getenv("MONGO_URI")
    if not uri:
        raise RuntimeError("MONGO_URI is required (local .env or environment)")
    client = MongoClient(uri, serverSelectionTimeoutMS=10000)
    return client, client["university_assistant"]["university_documents"]


def _print_notice(record, detailed=False):
    summary = {
        "notice_id": record.get("notice_id"),
        "title": record.get("title"),
        "status": record.get("status"),
        "source_url": record.get("url"),
        "processed_at": str(record.get("processed_at")),
        "requires_chunking": record.get("requires_chunking", False),
        "chunks": len(record.get("chunk_extractions") or []),
        "warnings": review_warnings(record),
    }
    if detailed:
        data = record.get("structured_data") or {}
        summary["structured_data"] = data
        summary["raw_text_excerpt"] = (record.get("raw_text") or "")[:1500]
        summary["raw_text_length"] = len(record.get("raw_text") or "")
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Inspect and approve/reject long PDFs")
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list")
    listing.add_argument("--limit", type=int, default=40)
    show = sub.add_parser("show")
    show.add_argument("notice_id")
    for verb in ("approve", "reject"):
        action = sub.add_parser(verb)
        action.add_argument("notice_id")
        action.add_argument("--reviewer", required=True)
        action.add_argument("--notes", required=True)
        if verb == "approve":
            action.add_argument("--acknowledge-warnings", action="store_true")
    args = parser.parse_args(argv)
    client, collection = _db()
    try:
        if args.command == "list":
            if not 1 <= args.limit <= 100:
                parser.error("--limit must be between 1 and 100")
            query = {"status": "review_required"}
            count = collection.count_documents(query)
            print(f"Pending review: {count}")
            for record in collection.find(query).sort("processed_at", 1).limit(args.limit):
                _print_notice(record)
            return 0

        query = {"notice_id": args.notice_id}
        record = collection.find_one(query)
        if not record:
            print("No matching notice_id found", file=sys.stderr)
            return 1
        if args.command == "show":
            _print_notice(record, detailed=True)
            return 0

        if args.command == "approve":
            update = approval_update(
                record, args.reviewer, args.notes,
                acknowledge_warnings=args.acknowledge_warnings,
            )
        else:
            update = rejection_update(record, args.reviewer, args.notes)

        # Optimistic concurrency check: another reviewer or a refreshed PDF
        # must not invalidate this human approval.
        result = collection.update_one(
            {"_id": record["_id"], "status": "review_required",
             "pdf_sha256": record.get("pdf_sha256")},
            update,
        )
        if result.modified_count != 1:
            raise RuntimeError("Review record changed or was already reviewed; reload it")
        print(f"{args.command}d {args.notice_id} by {args.reviewer}.")
        if args.command == "approve":
            print("Now run the Module3 indexer or scheduled sync to make it searchable.")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError) as error:
        print(f"Review failed: {error}", file=sys.stderr)
        raise SystemExit(1)
