"""Optional LIVE 50-question UniAI evaluation (never run automatically in CI).

Example:
  python backend/evaluation/run_50.py --base-url https://YOUR-RENDER-URL --run-live

This script makes up to 50 actual POST /api/chat requests and writes a CSV.
It does not grade factual correctness automatically: each answer must be
cross-checked by a reviewer against the *specific official PDF*.
"""
import argparse
import csv
import json
from pathlib import Path
import time
from urllib import error, parse, request
import uuid


FIXTURE = Path(__file__).with_name("questions_50.json")
FIELDS = [
    "id", "category", "question", "expected_behavior", "status",
    "latency_seconds", "response", "sources", "source_domain_check",
    "manual_verdict", "reviewer_notes",
]


def load_questions():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rows = data["questions"]
    ids = [q["id"] for q in rows]
    if len(rows) != 50 or len(set(ids)) != 50:
        raise ValueError("Expected exactly 50 questions with distinct identifiers")
    return rows


def valid_sources(sources):
    if not isinstance(sources, list):
        return False
    for item in sources:
        if not isinstance(item, dict):
            return False
        url = str(item.get("url") or "")
        parsed = parse.urlsplit(url)
        if (parsed.scheme != "https" or
            parsed.hostname not in {"makautwb.ac.in", "www.makautwb.ac.in"}):
            return False
    return True


def verify_revision(base_url, expected_sha):
    """Fail BEFORE making billable LLM requests if Render deploy is stale."""
    expected_sha = str(expected_sha or "").lower().strip()
    if not (7 <= len(expected_sha) <= 40 and
            all(c in "0123456789abcdef" for c in expected_sha)):
        raise ValueError("Expected git commit must be a 7-40 character SHA")
    endpoint = base_url.rstrip("/") + "/health"
    try:
        with request.urlopen(endpoint, timeout=45) as resp:
            payload = json.load(resp)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Could not verify deployed revision at {endpoint}: {exc}") from exc
    actual = str(payload.get("revision") or "").lower().strip()
    if not actual.startswith(expected_sha):
        raise RuntimeError(
            f"Wrong Render version: /health revision is {actual!r}, "
            f"expected prefix {expected_sha!r}. Check Render Deploys and "
            "wait for the intended commit to be live before evaluation."
        )
    print(f"Deployment verified: {actual}", flush=True)


def execute(base_url, output_path, timeout_seconds=135, delay_seconds=0.5, only_ids=None):
    questions = load_questions()
    if only_ids:
        wanted = set(only_ids)
        actual_ids = {q["id"] for q in questions}
        unknown = sorted(wanted - actual_ids)
        if unknown:
            raise ValueError(f"Unknown question IDs: {', '.join(unknown)}")
        questions = [q for q in questions if q["id"] in wanted]
    base = base_url.rstrip("/")
    if not base.startswith("https://") and not base.startswith("http://localhost"):
        raise ValueError("Use an HTTPS backend URL (or localhost for development)")
    conversations = {}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        for q in questions:
            cid = conversations.setdefault(q["conversation"], uuid.uuid4().hex)
            payload = {
                "question": q["question"],
                "conversation_id": cid,
                "request_id": uuid.uuid4().hex,
            }
            started = time.monotonic()
            status = "error"
            response_text = ""
            sources = []
            try:
                req = request.Request(
                    f"{base}/api/chat",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with request.urlopen(req, timeout=timeout_seconds) as resp:
                    response = json.load(resp)
                    status = str(resp.status)
                response_text = str(response.get("answer") or "")
                sources = response.get("sources") or []
            except error.HTTPError as exc:
                status = f"HTTP_{exc.code}"
                response_text = exc.read(1000).decode("utf-8", errors="replace")
            except (OSError, ValueError) as exc:
                response_text = f"{type(exc).__name__}: {str(exc)[:400]}"
            row = {
                "id": q["id"], "category": q["category"],
                "question": q["question"],
                "expected_behavior": q["expected_behavior"],
                "status": status,
                "latency_seconds": round(time.monotonic() - started, 2),
                "response": response_text,
                "sources": json.dumps(sources, ensure_ascii=False),
                "source_domain_check": "pass" if valid_sources(sources) else "fail",
                "manual_verdict": "not_reviewed",
                "reviewer_notes": "",
            }
            writer.writerow(row)
            stream.flush()
            print(f'{q["id"]}: {status}, sources={len(sources) if isinstance(sources, list) else "?"}', flush=True)
            time.sleep(delay_seconds)
    print(f"Evaluation results saved to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Run UniAI 50-question LIVE evaluation")
    parser.add_argument("--base-url", help="Deployed FastAPI root URL")
    parser.add_argument("--out", default="backend/evaluation/results_50.csv")
    parser.add_argument("--run-live", action="store_true",
                        help="Explicitly confirm real backend requests")
    parser.add_argument("--expect-revision",
                        help="Require deployed /health revision to match this git SHA prefix before requests")
    parser.add_argument("--only", nargs="+", metavar="ID",
                        help="Only run selected IDs, e.g. --only Q03 Q17 Q23 Q24")
    args = parser.parse_args()
    if not args.run_live or not args.base_url:
        parser.error("No live requests made. Set --base-url and --run-live to execute.")
    if args.expect_revision:
        verify_revision(args.base_url, args.expect_revision)
    execute(args.base_url, Path(args.out), only_ids=args.only)


if __name__ == "__main__":
    main()
