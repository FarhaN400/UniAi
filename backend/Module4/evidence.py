import re
from datetime import date, datetime
from urllib.parse import urlparse


_ROUND_WORDS = {
    "first": 1,
    "1st": 1,
    "second": 2,
    "2nd": 2,
    "third": 3,
    "3rd": 3,
}
_MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}
_FACT_TERMS = (
    "admission", "application", "campus", "closing", "date", "deadline",
    "document", "eligibility", "fee", "guarantee", "issue",
    "merit", "package", "placement", "reporting", "round", "salary",
    "scholarship", "time",
)


def _normalize_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return ", ".join(
            f"{key}: {_normalize_value(item)}"
            for key, item in value.items()
            if item is not None
        )
    if isinstance(value, (list, tuple)):
        return "; ".join(_normalize_value(item) for item in value if item is not None)
    return str(value).strip()


def _flatten_fields(value, prefix=""):
    fields = []
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            fields.extend(_flatten_fields(item, path))
    elif isinstance(value, (list, tuple)):
        items = [_normalize_value(item) for item in value if item is not None]
        if items:
            fields.append((prefix, "; ".join(items)))
    elif value is not None and str(value).strip():
        fields.append((prefix, _normalize_value(value)))
    return fields


def _notice_id(record):
    value = record.get("notice_id")
    return str(value).strip() if value is not None else ""


def _date_months(text):
    normalized = text.casefold()
    months = set()
    for word, month_number in _MONTHS.items():
        if re.search(
            rf"\b{word}\b(?:[\s,/-]+\d{{1,4}}|\s+\d{{1,2}}\s+to\b)"
            rf"|\b\d{{1,4}}[\s,/-]+{word}\b",
            normalized,
        ):
            months.add(month_number)
    for pattern in (
        r"\b\d{1,2}[-/](\d{1,2})[-/]\d{4}\b",
        r"\b\d{4}[-/](\d{1,2})[-/]\d{1,2}\b",
    ):
        for match in re.finditer(pattern, text):
            month = int(match.group(1))
            if 1 <= month <= 12:
                months.add(month)
    return months


def _currencies(text):
    normalized = text.casefold()
    currencies = set()
    if "₹" in text or re.search(r"\b(?:rs\.?|inr)\b", normalized):
        currencies.add("INR")
    if "$" in text or re.search(r"\b(?:usd|dollars?)\b", normalized):
        currencies.add("USD")
    if "€" in text or re.search(r"\b(?:eur|euros?)\b", normalized):
        currencies.add("EUR")
    if "£" in text or re.search(r"\b(?:gbp|pounds?)\b", normalized):
        currencies.add("GBP")
    return currencies


def _fact_terms(text):
    words = re.findall(r"[a-z]+", text.casefold())
    return {
        term
        for term in _FACT_TERMS
        if any(word.startswith(term) for word in words)
    }


def _requested_rounds(question):
    text = str(question or "").lower()
    rounds = set()
    for word, number in _ROUND_WORDS.items():
        if re.search(rf"\b{word}\s*[- ]?round\b|\bround\s*{word}\b", text):
            rounds.add(number)
    numeric_round = re.search(r"\bround\s*(?:no\.?\s*)?(1|2|3)\b", text)
    if numeric_round:
        rounds.add(int(numeric_round.group(1)))
    return rounds


def _record_rounds(record):
    data = record.get("structured_data") or {}
    prioritized = " ".join(
        str(value or "")
        for value in (
            record.get("title"),
            data.get("title"),
            data.get("admission_round"),
            data.get("round"),
        )
    ).lower().strip()

    def extract_rounds(search_text):
        rounds = set()
        for word, number in _ROUND_WORDS.items():
            if re.search(rf"\b{word}\s*[- ]?round\b|\bround\s*{word}\b", search_text):
                rounds.add(number)
        match = re.search(r"\bround\s*(?:no\.?\s*)?(1|2|3)\b", search_text)
        if match:
            rounds.add(int(match.group(1)))
        return rounds

    rounds = extract_rounds(prioritized)
    if rounds:
        return rounds
    full_text = " ".join(
        str(value or "") for value in (data, record.get("raw_text"))
    ).lower()
    return extract_rounds(full_text)


def filter_explicit_notice_scope(question, records):
    """Filter candidates only when a requested year or admission round is explicit."""
    text = str(question or "")
    year_match = re.search(r"\b(20\d{2})\b", text)
    year = year_match.group(1) if year_match else None
    rounds = _requested_rounds(text)
    if year is None and not rounds:
        return list(records)

    # An admission-round match must also match the named entrance examination.
    # Use the notice identity fields rather than incidental links in OCR text.
    query_lower = text.casefold()
    requested_exam = None
    for exam, pattern in (
        ("wbjeeb", r"\bwbjeeb?\b"),
        ("jeca", r"\bjeca\b"),
        ("jelet", r"\bjelet\b"),
        ("pget", r"\bpget\b"),
        ("jemat", r"\bjemat\b"),
    ):
        if re.search(pattern, query_lower):
            requested_exam = exam
            break

    selected = []
    for record in records:
        data = record.get("structured_data") or {}
        searchable = " ".join(
            str(value or "")
            for value in (
                record.get("title"),
                record.get("raw_text"),
                record.get("url"),
                data,
            )
        )
        if requested_exam:
            identity = " ".join(str(v or "") for v in (
                record.get("title"), data.get("title"),
                data.get("target_audience"), data.get("notice_type"),
            )).casefold()
            if requested_exam == "wbjeeb":
                exam_ok = bool(re.search(r"\bwbjeeb?\b", identity))
            else:
                exam_ok = bool(re.search(rf"\b{requested_exam}\b", identity))
            if not exam_ok:
                continue
        if year and year not in searchable:
            continue
        if rounds and not (rounds & _record_rounds(record)):
            continue
        selected.append(record)
    return selected


def build_evidence_bundle(records, question, context_builder, snippet_extractor):
    """Build an ID-keyed context and an evidence-reference catalog."""
    blocks = []
    evidence = {}
    records_by_id = {}

    for record in records:
        notice_id = _notice_id(record)
        if not notice_id or notice_id in records_by_id:
            continue
        records_by_id[notice_id] = record
        data = record.get("structured_data") or {}
        title = data.get("title") or record.get("title") or "Untitled notice"
        block = [
            f"NOTICE_ID: {notice_id}",
            f"Official title: {title}",
        ]
        if data.get("issue_date") is not None:
            block.append(f"Official issue date: {_normalize_value(data['issue_date'])}")
        if record.get("url"):
            block.append(f"Primary official PDF URL: {record['url']}")
        block.append("Evidence references:")

        facts = _flatten_fields(data)
        if not any(name == "title" for name, _ in facts):
            facts.insert(0, ("title", str(title)))
        for index, (name, value) in enumerate(facts, start=1):
            reference = f"N{len(records_by_id)}-E{index}"
            fact = f"{name}: {value}"
            evidence[reference] = {"notice_id": notice_id, "text": fact}
            block.append(f"[{reference}] {fact}")

        raw_text = record.get("raw_text") or ""
        if raw_text and question:
            excerpts = snippet_extractor(
                raw_text,
                question,
                max_snippets=2,
                max_chars=400,
            )
            for excerpt_index, excerpt in enumerate(excerpts, start=1):
                reference = f"N{len(records_by_id)}-R{excerpt_index}"
                fact = f"Official notice excerpt: {excerpt}"
                evidence[reference] = {"notice_id": notice_id, "text": fact}
                block.append(f"[{reference}] {fact}")

        block.append(
            "Context excerpt:\n" + context_builder([record], question=question)
        )
        blocks.append("\n".join(block))

    return "\n\n".join(blocks), evidence, records_by_id


def _significant_numbers(value):
    """Normalize dates, ranges and time tokens without trusting model citations."""
    return {str(int(x)) for x in re.findall(r"\d+", value)}


def validate_claims(claims, evidence, records_by_id, debug=False):
    """Validate claims against ORIGINAL server-side evidence, not model quotes.

    Strict structural and lexical checks reduce unsupported citations but are NOT
    a full semantic factuality guarantee; original PDFs remain authoritative.
    """
    if not isinstance(claims, list):
        return []

    approved = []
    for position, claim in enumerate(claims, 1):
        def reject(why):
            if debug:
                print(f"[EVIDENCE] claim {position} rejected: {why}", flush=True)

        if not isinstance(claim, dict):
            reject("claim is not an object")
            continue
        statement = claim.get("text")
        ids = claim.get("notice_ids")
        refs = claim.get("evidence_refs")
        if not isinstance(statement, str) or not statement.strip():
            reject("missing claim text")
            continue
        if not isinstance(ids, list) or len(ids) != 1:
            reject("requires one notice ID")
            continue
        notice_id = str(ids[0])
        if notice_id not in records_by_id:
            reject("unknown notice ID")
            continue
        if not isinstance(refs, list) or not refs or len(refs) > 12:
            reject("missing/invalid evidence_refs")
            continue
        if any(not isinstance(ref, str) for ref in refs):
            reject("non-string evidence reference")
            continue
        refs = list(dict.fromkeys(refs))
        if any(ref not in evidence or evidence[ref]["notice_id"] != notice_id for ref in refs):
            reject("unknown or cross-notice reference")
            continue

        # Evidence is looked up locally. Model-generated quotations are ignored.
        original_text = " ".join(evidence[ref]["text"] for ref in refs)
        missing_numbers = _significant_numbers(statement) - _significant_numbers(original_text)
        if missing_numbers:
            reject(f"unsupported numbers: {sorted(missing_numbers)}")
            continue
        missing_months = _date_months(statement) - _date_months(original_text)
        if missing_months:
            reject(f"unsupported date months: {sorted(missing_months)}")
            continue
        if "%" in statement and "%" not in original_text and "percent" not in original_text.casefold():
            reject("unsupported percentage")
            continue
        if not _currencies(statement).issubset(_currencies(original_text)):
            reject("unsupported currency")
            continue
        # Primary PDF URL comes from record metadata; other links must be cited.
        urls = {u.rstrip(".,;:") for u in re.findall(r"https?://[^\s<>\])}]+", statement, re.I)}
        primary_url = str(records_by_id[notice_id].get("url") or "").rstrip(".,;:")
        supported_urls = {u.rstrip(".,;:") for u in re.findall(r"https?://[^\s<>\])}]+", original_text, re.I)}
        if primary_url:
            supported_urls.add(primary_url)
        if not urls.issubset(supported_urls):
            reject("unsupported URL")
            continue
        # Prevent claiming WBJEEB evidence supports JECA (or vice versa).
        exam_tokens = ("wbjeeb", "wbjee", "jeca", "jelet", "pget", "jemat")
        claim_lower, cited_lower = statement.casefold(), original_text.casefold()
        if any(re.search(rf"\b{tok}\b", claim_lower) and not re.search(rf"\b{tok}\b", cited_lower)
               for tok in exam_tokens):
            reject("admission exam not established by cited references")
            continue
        # Block unsupported absence/guarantee statements rather than deriving
        # them from absent structured fields.
        if re.search(r"\b(not specified|not mentioned|does not (?:state|specify|mention)|no guaranteed)\b", statement, re.I):
            if not re.search(r"\b(not specified|not mentioned|does not (?:state|specify|mention)|no guaranteed)\b", original_text, re.I):
                reject("negative/absence claim not explicitly evidenced")
                continue
        approved.append({"text": statement.strip(), "notice_ids": [notice_id]})
        if debug:
            print(f"[EVIDENCE] claim {position} accepted; refs={refs}", flush=True)
    return approved



# --------------------------------------------------
# Narrow missing-amount guidance from trusted notice data
# --------------------------------------------------

def _known_value(value):
    """Whether a structured field actually supplies a value (including zero)."""
    return value is not None and str(value).strip().casefold() not in {
        "", "none", "null", "n/a", "not provided", "not specified", "unknown",
    }


def _has_stated_amount(record, category):
    """Avoid a missing-value answer when relevant amount evidence is present.

    Intentionally conservative: an uncertain match delegates to ordinary RAG
    rather than risk saying a stated amount could not be found.
    """
    data = record.get("structured_data") or {}
    fees = data.get("fees") or {}
    if category == "application":
        candidates = [data.get("application_fee"), data.get("application_fee_amount")]
        if isinstance(fees, dict):
            candidates += [fees.get("application_fee"), fees.get("application_fee_amount")]
            # The generic field is ambiguous, so do not conclude it is absent.
            candidates.append(fees.get("amount"))
        if any(_known_value(v) for v in candidates):
            return True
        source = " ".join([str(record.get("raw_text") or ""),
                           " ".join(value for _, value in _flatten_fields(data))])
        name = r"application[\s-]*fees?"
    else:
        candidates = [data.get(k) for k in (
            "guaranteed_placement", "placement_package", "guaranteed_package",
            "placement_salary", "salary_package")]
        if any(_known_value(v) for v in candidates):
            return True
        source = " ".join([str(record.get("raw_text") or ""),
                           " ".join(value for _, value in _flatten_fields(data))])
        name = r"(?:guaranteed[\s-]*placement(?:[\s-]*package)?|placement[\s-]*package)"

    money = r"(?:₹|rs\.?|inr|\$)\s*[\d,]+(?:\.\d+)?|[\d,]+(?:\.\d+)?\s*(?:rupees?|inr|lpa|lakhs?)\b"
    # Either 'Application fee: Rs. 500' or 'Rs. 500 application fee'.
    if re.search(rf"\b{name}\b.{{0,90}}?(?:{money}|\bfree\b|\bnil\b|\bzero\b)", source, re.I | re.S):
        return True
    if re.search(rf"(?:{money}).{{0,70}}?\b{name}\b", source, re.I | re.S):
        return True
    return False


def _official_admission_fee_url(record):
    """Use an actual MAKAUT URL appearing alongside admission-fee guidance."""
    data = record.get("structured_data") or {}
    texts = [value for _, value in _flatten_fields(data)]
    raw = str(record.get("raw_text") or "")
    if raw:
        texts.append(raw)
    for source in texts:
        if not re.search(r"\badmission[\s-]*fees?\b", source, re.I):
            continue
        for found in re.finditer(r"https?://[^\s<>\]\[\)\(\}\{]+", source, re.I):
            url = found.group(0).rstrip(".,;:")
            host = (urlparse(url).hostname or "").lower()
            if host != "makautwb.ac.in" and not host.endswith(".makautwb.ac.in"):
                continue
            nearby = source[max(0, found.start() - 150):found.end() + 150]
            if re.search(r"\badmission[\s-]*fees?\b", nearby, re.I):
                return url
    return None


def missing_amount_guidance(question, record):
    """A cautious answer for a *specific* missing amount in one retrieved notice.

    Never says that the original PDF categorically contains no value: OCR and
    extraction can be incomplete. The authoritative source remains the notice.
    Returns None for all other questions or where an amount may be available.
    """
    if not isinstance(record, dict) or not _notice_id(record):
        return None
    q = str(question or "")
    if re.search(r"\bapplication[\s-]*fees?\b", q, re.I):
        if _has_stated_amount(record, "application"):
            return None
        text = (
            "I couldn't find an application-fee amount in the available "
            "information for this notice."
        )
        fee_url = _official_admission_fee_url(record)
        if fee_url:
            text += (
                " The notice separately directs students to admission-fee "
                f"information at {fee_url}. That does not establish an "
                "application-fee amount."
            )
        return text

    # Supported also for the final regression test, without claiming that a
    # placement guarantee is definitely absent from an unread original PDF.
    if (re.search(r"\bguaranteed\b", q, re.I)
            and re.search(r"\b(?:placement|package|salary|ctc)\b", q, re.I)):
        if _has_stated_amount(record, "placement"):
            return None
        return (
            "I couldn't find a guaranteed placement-package amount in the "
            "available information for this notice. Do not interpret this "
            "notice as a guarantee of any particular salary."
        )
    return None

def sources_from_records(records):
    """Return deduplicated primary-PDF source objects from supporting records."""
    sources = []
    seen_urls = set()
    for record in records:
        if not _notice_id(record):
            continue
        url = record.get("url")
        if not isinstance(url, str) or not re.match(r"^https?://", url, re.I):
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)

        data = record.get("structured_data") or {}
        issue_date = data.get("issue_date")
        if isinstance(issue_date, (date, datetime)):
            issue_date = issue_date.isoformat()
        sources.append({
            "title": data.get("title") or record.get("title") or "Untitled notice",
            "url": url,
            "date": issue_date,
        })
    return sources
