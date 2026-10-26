"""UniAI Module 1: discover new MAKAUT notices and optionally check PDF revisions.

Maintains the original notice_id = SHA256(URL) identity and public entry points.
"""
import hashlib
import os
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

BASE_URL = "https://makautwb.ac.in/"
NOTICE_PAGE = "https://makautwb.ac.in/page.php?id=340"
INVALID_NOTICE_IDS = {
    "a9dd4d2604d2a16028d40a7213745cb93ddef51fe8eb44877b3c75ab5b2af333"
}
MAX_PDF_BYTES = 25 * 1024 * 1024

MONGO_URI = os.getenv("MONGO_URI")
if not MONGO_URI:
    raise ValueError("MONGO_URI not found in environment")
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=15000)
notices_collection = client["university_assistant"]["university_documents"]
notices_collection.create_index("notice_id", unique=True)


def _is_official_url(url):
    parsed = urlsplit(url)
    return (parsed.scheme == "https" and
            parsed.hostname in {"makautwb.ac.in", "www.makautwb.ac.in"})


def get_makautwb_notices():
    response = requests.get(NOTICE_PAGE, timeout=25)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    notices = []
    seen_urls = set()
    for anchor in soup.select("a.text-danger[href]"):
        title = anchor.get_text(" ", strip=True)
        url = urljoin(BASE_URL, anchor["href"].strip())
        if not title or not _is_official_url(url) or url in seen_urls:
            continue
        seen_urls.add(url)
        adjacent = anchor.find_next_sibling("img")
        notices.append({
            "title": title,
            "url": url,
            "flagged_new_on_site": bool(adjacent and "new-08-june" in adjacent.get("src", "")),
        })
    if not notices:
        raise RuntimeError("No notice links found: MAKAUT page markup may have changed")
    return notices


def add_notice_id(notice):
    notice["notice_id"] = hashlib.sha256(notice["url"].encode("utf-8")).hexdigest()
    return notice


def store_notice(notice):
    """Upsert by immutable URL-derived notice ID; never reset processed records.

    Return True only if a new valid notice was inserted, as in original Module 1.
    """
    notice = add_notice_id(dict(notice))
    now = datetime.now(timezone.utc)
    invalid = notice["notice_id"] in INVALID_NOTICE_IDS
    # MongoDB prohibits updating the same path through both $set and
    # $setOnInsert in one update, even when an existing record is matched.
    # These two always-refresh fields belong exclusively to $set.
    insert_only = {key: value for key, value in notice.items()
                   if key != "flagged_new_on_site"}
    payload = {
        **insert_only,
        "detected_at": now,
        "status": "invalid" if invalid else "new",
        "pinecone_indexed": False,
        "processing_attempts": 0,
    }
    if invalid:
        payload["processing_error"] = "Known invalid PDF: " + notice["url"]
    result = notices_collection.update_one(
        {"notice_id": notice["notice_id"]},
        {
            "$setOnInsert": payload,
            "$set": {"last_seen_at": now, "flagged_new_on_site": notice["flagged_new_on_site"]},
        },
        upsert=True,
    )
    return result.upserted_id is not None and not invalid


def _pdf_digest(url):
    """Hash an official PDF without writing it to persistent local storage."""
    if not _is_official_url(url):
        raise ValueError("Refusing to download PDF from a non-MAKAUT URL")
    with requests.get(url, timeout=(10, 40), stream=True) as response:
        response.raise_for_status()
        content_length = int(response.headers.get("Content-Length", 0) or 0)
        if content_length > MAX_PDF_BYTES:
            raise ValueError("PDF exceeds 25 MB limit")
        checksum = hashlib.sha256()
        total = 0
        header = b""
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue
            if not header:
                header = chunk[:5]
            total += len(chunk)
            if total > MAX_PDF_BYTES:
                raise ValueError("PDF exceeds 25 MB limit")
            checksum.update(chunk)
        if header != b"%PDF-":
            raise ValueError("Downloaded content is not a PDF")
        return checksum.hexdigest()


def recheck_existing_pdf_versions(limit=0):
    """Check a small rotating sample of processed PDF hashes each cycle.

    This is an optional *bounded* check. It doesn't guarantee immediate updates
    for PDFs changed without a URL change.
    """
    limit = max(0, int(limit))
    if not limit:
        return {"checked": 0, "changed": 0, "errors": 0}
    cursor = (notices_collection.find({
        # Review-pending PDFs may also change; invalidate pending approvals.
        "status": {"$in": ["processed", "review_required"]},
        "pdf_sha256": {"$type": "string"}
    }).sort([("last_content_checked_at", 1), ("detected_at", 1)]).limit(limit))
    counters = {"checked": 0, "changed": 0, "errors": 0}
    for record in cursor:
        counters["checked"] += 1
        try:
            digest = _pdf_digest(record["url"])
            now = datetime.now(timezone.utc)
            if digest != record["pdf_sha256"]:
                result = notices_collection.update_one(
                    {"_id": record["_id"], "status": record["status"], "pdf_sha256": record["pdf_sha256"]},
                    {
                        "$set": {
                            "status": "new", "pinecone_indexed": False,
                            "processing_attempts": 0,
                            "last_content_checked_at": now,
                            "content_change_detected_at": now,
                        },
                        "$unset": {
                            "next_retry_at": "", "processing_error": "",
                            "review_approved_at": "", "review_approved_by": "",
                            "review_notes": "", "review_acknowledged_warnings": "",
                        },
                    },
                )
                counters["changed"] += int(result.modified_count > 0)
                if result.modified_count:
                    print(f"[Module1] Changed PDF detected: {record['url']}")
            else:
                notices_collection.update_one(
                    {"_id": record["_id"], "status": record["status"],
                     "pdf_sha256": record["pdf_sha256"]},
                    {"$set": {"last_content_checked_at": now}}
                )
        except Exception as exc:
            counters["errors"] += 1
            print(f"[Module1] PDF version check failed for {record.get('url')}: {exc}")
    return counters


def run_monitor_cycle():
    """Return a discovery report; propagate failures so Actions can alert."""
    discovered = get_makautwb_notices()
    new = [n for n in discovered if store_notice(n)]
    report = {"seen": len(discovered), "new": len(new), "existing": len(discovered) - len(new)}
    print(f"[Module1] Found {report['seen']} notices; {report['new']} new")
    for notice in new[:10]:
        print(f"  + {notice['title']}: {notice['url']}")
    return report


if __name__ == "__main__":
    try:
        print(run_monitor_cycle())
    finally:
        client.close()
