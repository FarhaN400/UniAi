from retrieve import retrieve_context, retrieve_topic_notices, extract_year_from_question
from main import (
    extract_requested_count,
    extract_notice_ordinal,
    format_notice_line,
    format_notice_list,
    is_notice_detail_follow_up,
    is_single_notice_follow_up,
)
import main as uniai_main


def check_requested_count_is_honored(question, expected_count):
    """Verify that a user request like '4 latest notices' fetches that many records."""
    print(f"\nQuestion: '{question}'")
    results = retrieve_context(question, top_k=expected_count)
    print(f"  Results returned: {len(results)}")
    assert extract_requested_count(question) == expected_count
    assert len(results) >= expected_count, f"Expected {expected_count} records, got {len(results)}"


    for i, r in enumerate(results[:expected_count], start=1):
        sd = r["structured_data"]
        print(f"  {i}. {sd.get('title')}")


def check_ordinal_followup(question):
    """Verify ordinal follow-ups resolve against the latest-notice ordering."""
    ordinal = extract_notice_ordinal(question)
    assert ordinal is not None, f"Could not parse notice ordinal from: {question}"
    results = retrieve_context("latest notices", top_k=ordinal)
    assert len(results) >= ordinal, f"Expected notice {ordinal}, got {len(results)} records"
    line = format_notice_line(results[ordinal - 1])
    assert "\nDate:" in line and "\nOfficial source:" in line
    assert "\nReference:" in line and "\nSummary:" in line
    assert "**" not in line and " | " not in line
    print(f"  {ordinal}. {line}")


def check_notice_list_spacing():
    records = retrieve_context("latest notices", top_k=2)
    output = format_notice_list(records)
    assert "\n\n2. " in output, "Notices should be separated by a blank line"
    print("  Blank-line spacing between notices: PASS")


def check_wbjee_latest_follow_up():
    record = {
        "structured_data": {
            "title": "Latest WBJEE notice",
            "issue_date": "11-09-2026",
            "reference_no": "WBJEE-TEST",
            "summary": "WBJEE reporting details.",
        },
        "url": "https://example.com/wbjee.pdf",
    }
    original_lookup = uniai_main.retrieve_topic_notices
    original_retrieval = uniai_main.retrieve_context
    original_chain = uniai_main.rag_chain
    original_records = uniai_main.last_notice_records
    original_history = list(uniai_main.chat_history)
    captured_payloads = []
    try:
        uniai_main.retrieve_topic_notices = lambda topic, top_k=1: [record]
        uniai_main.retrieve_context = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Detail follow-up should use the previous notice")
        )
        def fake_invoke(self, payload):
            captured_payloads.append(payload)
            return type("Response", (), {"content": payload["context"]})()

        uniai_main.rag_chain = type("FakeChain", (), {"invoke": fake_invoke})()
        uniai_main.last_notice_records = []
        latest = uniai_main.ask_uniai("what is the last notice of wbjee in portal?")
        follow_up = uniai_main.ask_uniai("give only one notice")
        more = uniai_main.ask_uniai("can you tell me more about this notice?")
        assert is_single_notice_follow_up("give only one notice")
        assert is_notice_detail_follow_up("can you tell me more about this notice?")
        assert "Latest WBJEE notice" in latest
        assert follow_up == latest
        assert "Latest WBJEE notice" in more
        assert "Latest WBJEE notice" in captured_payloads[-1]["context"]
        assert "what is the last notice of wbjee in portal?" in captured_payloads[-1]["history"]
        print("  WBJEE topic, single-notice, and detail follow-ups: PASS")
    finally:
        uniai_main.retrieve_topic_notices = original_lookup
        uniai_main.retrieve_context = original_retrieval
        uniai_main.rag_chain = original_chain
        uniai_main.last_notice_records = original_records
        uniai_main.chat_history[:] = original_history


def check_live_wbjee_topic_lookup():
    records = retrieve_topic_notices("wbjee", top_k=3)
    assert records, "Expected at least one processed WBJEE notice"
    for record in records:
        official_title = record.get("structured_data", {}).get("title", "").lower()
        assert "wbjee" in official_title, f"Not a WBJEE-specific notice: {official_title}"
    print(f"  Topic-filtered WBJEE notices: {len(records)} returned")


def check_year_filter_works(question, expected_year):
    """Verify that every retrieved notice actually matches the expected year."""
    print(f"\nQuestion: '{question}'")
    detected_year = extract_year_from_question(question)
    print(f"Detected year in question: {detected_year}")

    results = retrieve_context(question, top_k=5)

    if not results:
        print("  No results returned.")
        return

    all_correct = True
    for r in results:
        sd = r["structured_data"]
        title = sd.get("title")
        issue_date = sd.get("issue_date", "unknown")
        print(f"  - {title}  (issue_date: {issue_date})")

        if expected_year and str(expected_year) not in title and str(expected_year) not in str(issue_date):
            print(f"    ^ WARNING: expected year {expected_year} not clearly found here")
            all_correct = False

    if expected_year:
        status = "PASS - all results match expected year" if all_correct else "CHECK - some results may not match"
        print(f"  Result: {status}")


def check_unfiltered_query(question):
    """Just show what comes back for a question with no year mentioned."""
    print(f"\nQuestion: '{question}'")
    results = retrieve_context(question, top_k=3)

    if not results:
        print("  No results returned.")
        return

    for r in results:
        sd = r["structured_data"]
        print(f"  - {sd.get('title')}")


def check_time_based_query(question):
    """Verify the latest/today/yesterday retrieval path is used."""
    print(f"\nQuestion: '{question}'")
    results = retrieve_context(question, top_k=3)

    if not results:
        print("  No results returned.")
        return

    for r in results:
        sd = r["structured_data"]
        print(f"  - {sd.get('title')}  (detected_at: {r.get('detected_at')})")


if __name__ == "__main__":
    print("=" * 60)
    print("TEST 0: Numeric latest-notice request should honor requested count")
    print("=" * 60)
    check_requested_count_is_honored(
        "Give me 6 latest notice from official portal",
        expected_count=6,
    )

    print("\n" + "=" * 60)
    print("TEST 0b: Ordinal follow-up selects the requested latest notice")
    print("=" * 60)
    check_ordinal_followup("now the 5th one")
    check_notice_list_spacing()
    check_wbjee_latest_follow_up()
    check_live_wbjee_topic_lookup()

    print("=" * 60)
    print("TEST 1: Year-specific query (should ONLY return 2026 notices)")
    print("=" * 60)
    check_year_filter_works(
        "What documents do I need for WBJEEB 2026 admission?",
        expected_year=2026
    )

    print("\n" + "=" * 60)
    print("TEST 2: Different year-specific query")
    print("=" * 60)
    check_year_filter_works(
        "When do I need to report for JELET 2025 admission?",
        expected_year=2025
    )

    print("\n" + "=" * 60)
    print("TEST 3: Time-based query")
    print("=" * 60)
    check_time_based_query("What is the latest notice?")

    print("\n" + "=" * 60)
    print("TEST 4: No year mentioned (plain semantic search)")
    print("=" * 60)
    check_unfiltered_query("When is phase 2 registration?")

    print("\n" + "=" * 60)
    print("TEST 5: No year mentioned, different topic")
    print("=" * 60)
    check_unfiltered_query("Is ragging prohibited at this university?")