from retrieve import retrieve_context, extract_year_from_question


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


if __name__ == "__main__":
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
    print("TEST 3: No year mentioned (plain semantic search)")
    print("=" * 60)
    check_unfiltered_query("When is phase 2 registration?")

    print("\n" + "=" * 60)
    print("TEST 4: No year mentioned, different topic")
    print("=" * 60)
    check_unfiltered_query("Is ragging prohibited at this university?")