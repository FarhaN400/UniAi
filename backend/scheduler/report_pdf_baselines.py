"""UniAI Phase 5: read-only report for PDFs without SHA-256 baselines.

Place in backend/scheduler/report_pdf_baselines.py, then from backend/ run:
    python3 -m scheduler.report_pdf_baselines --limit 10
    python3 -m scheduler.report_pdf_baselines --skip 10 --limit 10

Produces a timestamped CSV in backend/phase5_reports. Nothing is written to
MongoDB or Pinecone. No LLM calls. Non-exact text is NEVER marked verified.
"""

import argparse
import csv
import hashlib
import io
import os
import re
import tempfile
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from dotenv import find_dotenv, load_dotenv
from pymongo import MongoClient
from pypdf import PdfReader

from Module2.ocr import extract_pdf_text, ocr_extract_pdf
from scheduler.backfill_pdf_hashes import download_pdf

MAX_PAGES = 12  # Do not OCR huge PDFs in a diagnostic batch.
FIELDS = [
    "notice_id", "title", "url", "classification", "method",
    "similarity_percent", "stored_chars", "current_chars", "pdf_sha256",
    "pages", "stored_only_numbers", "current_only_numbers",
    "structured_dates_not_found_in_current", "stored_example", "current_example", "error",
]


def words(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def number_counts(text):
    # Diagnostic only. OCR may split/reformat numbers; differences require review.
    return Counter(re.findall(r"\b\d+(?:[./:-]\d+)*\b", text))


def compare_text(stored, current):
    old, new = words(stored), words(current)
    # This score is for triage, not proof of factual correctness.
    matcher = SequenceMatcher(None, old[:4000], new[:4000], autojunk=True)
    return round(matcher.ratio() * 100, 2)


def first_text_change(stored, current):
    old, new = words(stored)[:2000], words(current)[:2000]
    matcher = SequenceMatcher(None, old, new, autojunk=True)
    diffs = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            diffs.append((max(i2 - i1, j2 - j1),
                          " ".join(old[i1:i2])[:160],
                          " ".join(new[j1:j2])[:160]))
    if not diffs:
        return "", ""
    _, before, after = max(diffs, key=lambda item: item[0])
    return before, after


def extract_structured_dates(sd):
    dates = sd.get("important_dates") or {}
    return [v for v in (sd.get("issue_date"), dates.get("start_date"),
                        dates.get("last_date")) if isinstance(v, str) and v.strip()]


def numeric_dates(text):
    # Compare parsed date values, tolerating punctuation and leading zeros.
    result = set()
    for day, month, year in re.findall(
        r"\b(\d{1,2})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(20\d{2})\b", text
    ):
        result.add((int(day), int(month), int(year)))
    return result


def dates_missing(sd, current):
    available = numeric_dates(current)
    missing = []
    for value in extract_structured_dates(sd):
        found = re.fullmatch(r"\s*(\d{1,2})[-./](\d{1,2})[-./](20\d{2})\s*", value)
        if found and tuple(map(int, found.groups())) not in available:
            missing.append(value)
    return "; ".join(missing)


def inspect(notice):
    row = {field: "" for field in FIELDS}
    row.update(notice_id=notice.get("notice_id", ""),
               title=notice.get("title", ""), url=notice.get("url", ""))
    stored = (notice.get("raw_text") or "").strip()
    row["stored_chars"] = len(stored)
    if not stored:
        row["classification"] = "REVIEW_NO_STORED_TEXT"
        return row

    try:
        payload = download_pdf(notice.get("url", ""))
        row["pdf_sha256"] = hashlib.sha256(payload).hexdigest()
        count = len(PdfReader(io.BytesIO(payload)).pages)
        row["pages"] = count
        if count > MAX_PAGES:
            row["classification"] = "REVIEW_LONG_PDF"
            return row

        with tempfile.NamedTemporaryFile(suffix=".pdf") as pdf_file:
            pdf_file.write(payload)
            pdf_file.flush()
            auto_text = extract_pdf_text(pdf_file.name).strip()
            if auto_text == stored:
                row.update(classification="EXACT_MATCH", method="automatic",
                           similarity_percent=100.0, current_chars=len(auto_text))
                return row
            ocr_text = ocr_extract_pdf(pdf_file.name).strip()
            if ocr_text == stored:
                row.update(classification="EXACT_MATCH", method="Tesseract OCR",
                           similarity_percent=100.0, current_chars=len(ocr_text))
                return row

        auto_similarity = compare_text(stored, auto_text)
        ocr_similarity = compare_text(stored, ocr_text)
        if ocr_similarity >= auto_similarity:
            current, method, score = ocr_text, "Tesseract OCR", ocr_similarity
        else:
            current, method, score = auto_text, "automatic", auto_similarity

        before_nums, after_nums = number_counts(stored), number_counts(current)
        before_example, after_example = first_text_change(stored, current)
        missing = dates_missing(notice.get("structured_data") or {}, current)
        row.update(
            classification="REVIEW_NUMBERS_OR_DATES" if before_nums != after_nums or missing else "REVIEW_TEXT_DIFF",
            method=method, similarity_percent=score, current_chars=len(current),
            stored_only_numbers="; ".join(list((before_nums - after_nums).elements())[:20]),
            current_only_numbers="; ".join(list((after_nums - before_nums).elements())[:20]),
            structured_dates_not_found_in_current=missing,
            stored_example=before_example,
            current_example=after_example,
        )
    except Exception as error:
        row["classification"] = "ERROR"
        row["error"] = f"{type(error).__name__}: {error}"[:300]
    return row


def run(limit, skip, output_dir):
    load_dotenv(find_dotenv(usecwd=True))
    uri = os.getenv("MONGO_URI")
    if not uri:
        raise RuntimeError("MONGO_URI missing")
    client = MongoClient(uri, serverSelectionTimeoutMS=10000)
    try:
        col = client["university_assistant"]["university_documents"]
        selection = {"status": "processed", "pdf_sha256": {"$exists": False}}
        total = col.count_documents(selection)
        cursor = col.find(selection).sort("_id", -1).skip(skip).limit(limit)
        rows = []
        print("--- PHASE 5 READ-ONLY PDF BASELINE REPORT ---")
        print(f"Remaining without hashes: {total} | Skip: {skip} | Limit: {limit}")
        for idx, notice in enumerate(cursor, start=1):
            print(f"[{idx}/{limit}] {notice.get('title', 'Untitled')}")
            row = inspect(notice)
            print(f"  {row['classification']} | similarity={row['similarity_percent'] or 'n/a'}%")
            rows.append(row)

        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        path = output / f"pdf_baseline_report_{stamp}.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)

        counts = Counter(row["classification"] for row in rows)
        print("\n--- SUMMARY ---")
        print(f"Checked: {len(rows)}")
        print(f"Exact matches: {counts['EXACT_MATCH']}")
        print(f"Need review: {sum(v for k, v in counts.items() if k.startswith('REVIEW_'))}")
        print(f"Errors: {counts['ERROR']}")
        print(f"CSV report: {path.resolve()}")
        print("MongoDB writes: 0 | Pinecone writes: 0 | Groq calls: 0")
        return path
    finally:
        client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=10, help="PDFs per run (1..25)")
    parser.add_argument("--skip", type=int, default=0, help="Skip first N unresolved notices")
    parser.add_argument("--output-dir", default=str(Path(__file__).resolve().parents[1] / "phase5_reports"))
    opts = parser.parse_args()
    if not 1 <= opts.limit <= 25:
        parser.error("--limit must be between 1 and 25")
    if opts.skip < 0:
        parser.error("--skip must not be negative")
    run(opts.limit, opts.skip, opts.output_dir)


if __name__ == "__main__":
    main()
