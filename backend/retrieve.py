#!/usr/bin/env python3
"""Apply a narrow, offline fix for UniAI's generic admission-notice searches.

Only backend/retrieve.py is modified. No network calls, API keys, database
changes, Git commands or external dependencies. A byte-for-byte backup is
created before writing. See --help.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
import re
import shutil
import sys

TOPIC_ANCHOR = '    "registration": ("registration", "register", "enrolment", "enrollment"),'
TOPIC_ENTRY = '    "admission": ("admission", "admissions", "addmission", "addmissions"),'
ROUTING_ANCHOR = '''    # WBJEE portal registration means WBJEE is the primary topic.
    if found & {"wbjee", "jeca", "jelet", "jemat", "pget", "cet"}:
        found.discard("registration")
    return found'''
ROUTING_REPLACEMENT = '''    # WBJEE portal registration means WBJEE is the primary topic.
    if found & {"wbjee", "jeca", "jelet", "jemat", "pget", "cet"}:
        found.discard("registration")
    # Protect already-working specialised searches: the generic word
    # "admission" must not override WBJEE/JELET, hostel, exam etc. routing.
    if found & (set(ADMISSION_TOPICS) | {
        "hostel", "frams", "holiday", "exam", "scholarship",
        "placement", "ragging", "affiliation",
    }):
        found.discard("admission")
    return found'''
TITLE_SCOPED_ANCHOR = '    title_scoped = {"hostel", "scholarship", "holiday", "exam"}'
TITLE_SCOPED_REPLACEMENT = '    title_scoped = {"hostel", "scholarship", "holiday", "exam", "admission"}'
TITLE_RULE_ANCHOR = '''    for topic in topics & title_scoped:
        if topic == "hostel" and not re.search(r"\\bhostels?\\b", title):'''
TITLE_RULE_REPLACEMENT = '''    for topic in topics & title_scoped:
        if topic == "admission":
            # Require an admission-related SUBJECT in a notice title, not a
            # stray "admission" mention in an unrelated summary/key point.
            if not re.search(
                r"\\b(?:admissions?|addmissions?|counsell?ing|"
                r"allott?ed\\s+students?|seat\\s+allotment)\\b", title
            ):
                return False
            # A refund or hostel-allotment circular is not the kind of
            # admission announcement requested by a generic notice search.
            if re.search(r"\\b(?:hostels?|refunds?|anti[- ]?ragging)\\b", title):
                return False
        if topic == "hostel" and not re.search(r"\\bhostels?\\b", title):'''


def replace_exactly_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Stopped safely: expected one {label} anchor, found {count}. "
            "Your retrieve.py differs from the reviewed GitHub version; no files changed."
        )
    return text.replace(old, new, 1)


def patch_source(original: str) -> str:
    if TOPIC_ENTRY in original:
        raise RuntimeError("Admission-topic patch already present; no files changed.")
    updated = replace_exactly_once(
        original, TOPIC_ANCHOR, TOPIC_ENTRY + "\n" + TOPIC_ANCHOR,
        "SEARCH_TOPICS insertion",
    )
    updated = replace_exactly_once(
        updated, ROUTING_ANCHOR, ROUTING_REPLACEMENT,
        "detect_search_topics routing",
    )
    updated = replace_exactly_once(
        updated, TITLE_SCOPED_ANCHOR, TITLE_SCOPED_REPLACEMENT,
        "title-scoped topics",
    )
    updated = replace_exactly_once(
        updated, TITLE_RULE_ANCHOR, TITLE_RULE_REPLACEMENT,
        "admission-title relevance rule",
    )
    return updated


def offline_tests(patched_code: str) -> None:
    """Exercise real patched functions without importing DB/Pinecone/Groq."""
    tree = ast.parse(patched_code, filename="retrieve.py")
    required_functions = {
        "_phrase_regex", "detect_search_topics", "_primary_search_text",
        "_secondary_search_text", "_exam_topics_in_text",
        "_search_topic_matches", "_question_scope_matches",
    }
    function_nodes = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in required_functions
    ]
    if {node.name for node in function_nodes} != required_functions:
        raise AssertionError("One or more expected retrieval functions are missing")
    topic_nodes = [
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "SEARCH_TOPICS"
                for t in node.targets)
    ]
    if len(topic_nodes) != 1:
        raise AssertionError("Cannot locate a unique SEARCH_TOPICS dictionary")
    scope = {
        "re": re,
        "ADMISSION_TOPICS": {"wbjee", "jeca", "jelet", "jemat", "pget", "cet"},
    }
    module = ast.Module(body=[*topic_nodes, *function_nodes], type_ignores=[])
    exec(compile(module, "retrieval_offline_checks", "exec"), scope)

    detect = scope["detect_search_topics"]
    relevant = scope["_search_topic_matches"]
    scope_matches = scope["_question_scope_matches"]
    tests = [
        ("Show me the five most recent admission notices.", "admission"),
        ("Give me the recent notice of addmission.", "admission"),
        ("List latest admissions circulars.", "admission"),
        ("Find WBJEE 2026 admission notices.", "wbjee"),
        ("Show recent hostel notices.", "hostel"),
    ]
    for q, expected in tests:
        assert expected in detect(q), f"Topic detection failed: {q!r}"
    assert "admission" not in detect("Find WBJEE 2026 admission notices."), (
        "WBJEE-specific handling must stay unchanged"
    )
    assert "admission" not in detect("Show hostel admission notices."), (
        "Hostel-specific handling must stay unchanged"
    )

    def record(title: str, summary: str = "") -> dict:
        return {"title": title, "structured_data": {"summary": summary}}

    good = [
        record("Admission and Reporting for WBJEEB-2026 Allotted Students"),
        record("Decentralised Admission Notice for Vacant Seats 2026"),
        record("JELET Admission Counselling and Seat Allotment Instructions 2026"),
    ]
    bad = [
        record("Constitution of Anti-Ragging Committee", "Admission helpdesk contact"),
        record("Hostel Allotment and Room Booking Notice", "Admission portal"),
        record("Application for Scholarship", "Admission process for students"),
        record("Guidelines for Refund of Admission Fees"),
        record("Semester Examination Timetable", "Students admitted in 2026"),
    ]
    queries = [
        "Show me the five most recent admission notices.",
        "Give me the recent notice of addmission.",
        "List latest admissions circulars.",
    ]
    for question in queries:
        topics = detect(question)
        for entry in good:
            assert relevant(entry, topics) and scope_matches(question, entry), (
                f"Expected admission notice excluded: {entry['title']}"
            )
        for entry in bad:
            assert not relevant(entry, topics), (
                f"Unrelated notice included: {entry['title']}"
            )
    print("PASS: 3 admission question variants; 3 relevant and 5 unrelated fixtures; existing named-topic routing.")


def main() -> int:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument(
        "--project-root", type=Path, default=Path.cwd(),
        help="UniAI repository root (default: current directory)",
    )
    cli.add_argument(
        "--dry-run", action="store_true",
        help="Validate and test the patch, but do not modify the file",
    )
    args = cli.parse_args()
    target = args.project_root.expanduser().resolve() / "backend" / "retrieve.py"
    if not target.is_file():
        print(f"ERROR: {target} not found. Run this script from the UniAI project root.", file=sys.stderr)
        return 1
    original = target.read_text(encoding="utf-8")
    try:
        patched = patch_source(original)
        offline_tests(patched)
    except (RuntimeError, AssertionError, SyntaxError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.dry_run:
        print("DRY RUN: all checks passed; no file changed.")
        return 0
    backup = target.with_name("retrieve.py.admission_fix.bak")
    if backup.exists():
        print(f"ERROR: backup already exists at {backup}; move it before retrying.", file=sys.stderr)
        return 1
    shutil.copy2(target, backup)
    target.write_text(patched, encoding="utf-8")
    print(f"UPDATED: {target}")
    print(f"BACKUP:  {backup}")
    print("Only backend/retrieve.py was edited. Test locally before committing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
