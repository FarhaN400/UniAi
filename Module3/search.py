from main import index


def _normalize_title(value):
    if value is None:
        return ""
    return " ".join(str(value).strip().lower().split())


def search_notices(question, top_k=3):
    results = index.search_records(
        namespace="notices",
        query={
            "inputs": {"text": question},
            "top_k": top_k
        }
    )

    if isinstance(results, dict):
        raw_hits = results.get("result", {}).get("hits", [])
    else:
        raw_hits = getattr(getattr(results, "result", None), "hits", [])

    seen_titles = set()
    unique_hits = []

    for match in raw_hits:
        payload = match.to_dict() if hasattr(match, "to_dict") else match
        title = payload.get("fields", {}).get("title")
        title_key = _normalize_title(title)

        if title_key and title_key in seen_titles:
            continue

        if title_key:
            seen_titles.add(title_key)
        unique_hits.append(payload)

    for match in unique_hits:
        print(f"Score: {match['_score']:.3f} | {match['fields'].get('title')}")

    if isinstance(results, dict):
        return {**results, "result": {**results.get("result", {}), "hits": unique_hits}}
    return {"result": {"hits": unique_hits}}


if __name__ == "__main__":
    print("Query: 'what documents do I need for WBJEE 2026 admission'")
    search_notices("what documents do I need for WBJEE 2026 admission")

    print("\nQuery: 'M.Pharm Direct and NCAHP Lateral Direct Admission'")
    search_notices("M.Pharm Direct and NCAHP Lateral Direct Admission")

    print("\nQuery: 'is ragging prohibited at this university'")
    search_notices("is ragging prohibited at this university")

    print("\nQuery: 'reporting dates for JELET 2025'")
    search_notices("reporting dates for JELET 2025")