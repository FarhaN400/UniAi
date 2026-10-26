"""Fee evidence extraction that keeps different payment categories separate.

This module intentionally uses only directly labelled text. The generic
structured_data.fees.amount does NOT prove an application or admission fee.
"""
import re


_FEE_LABEL = re.compile(
    r"\b(?P<kind>application|admission|registration|examination|exam|tuition|"
    r"processing|counselling|counseling)\s*[-\s]*fees?\b",
    re.IGNORECASE,
)
_MONEY = re.compile(
    r"(?:₹|Rs\.?|INR)\s*[0-9][0-9,]*(?:\.[0-9]+)?\b"
    r"|\b[0-9][0-9,]*(?:\.[0-9]+)?\s*(?:rupees?|INR)\b",
    re.IGNORECASE,
)
_NEGATED = re.compile(
    r"\b(?:not\s+(?:specified|mentioned|stated|listed|provided|available|"
    r"disclosed|applicable|charged|required)|"
    r"no\s+(?:separate\s+)?(?:application\s+|admission\s+)?fees?\b|"
    r"nil\b|free\b)",
    re.IGNORECASE,
)
_BOUNDARY = re.compile(r";+|(?<=[.!?])\s+(?=[A-Z])")


def query_fee_kind(question):
    """Only infer a fee type when the student names it unambiguously."""
    query = str(question or "")
    if re.search(r"\bapplication[\s-]*fees?\b|\bfees?\s+for\s+(?:an?\s+)?application\b", query, re.I):
        return "application"
    if re.search(r"\badmission[\s-]*fees?\b|\bfees?\s+for\s+admission\b", query, re.I):
        return "admission"
    if re.search(r"\bregistration[\s-]*fees?\b", query, re.I):
        return "registration"
    if re.search(r"\b(?:exam|examination)[\s-]*fees?\b", query, re.I):
        return "examination"
    return None


def _sections(text):
    """Split clauses without crossing from one fee sentence into another."""
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    merged = []
    for line in lines:
        if merged and re.search(r"\bfees?\s*[:=\-]?\s*$", merged[-1], re.I) and (
            _MONEY.match(line) or line[:1] in "(:"
        ):
            merged[-1] += " " + line
        else:
            merged.append(line)
    for line in merged:
        for clause in _BOUNDARY.split(line):
            clause = clause.strip()
            if clause:
                yield clause


def _directly_labeled_fee(text, kind):
    """Yield (quoted evidence, amount) only for explicitly associated money."""
    for section in _sections(text):
        labels = list(_FEE_LABEL.finditer(section))
        for index, label in enumerate(labels):
            label_kind = label.group("kind").casefold()
            if label_kind == "exam":
                label_kind = "examination"
            if label_kind != kind:
                continue

            # Another fee label ends this fee's scope even in the same sentence.
            end = labels[index + 1].start() if index + 1 < len(labels) else len(section)
            right = section[label.end():end]
            candidate = next((m for m in _MONEY.finditer(right) if m.start() <= 85), None)
            if candidate and not _NEGATED.search(right[:candidate.start()]):
                quote = section[label.start():min(end, label.end() + 160)].strip(" ,:-")
                yield quote, candidate.group(0).strip()
                continue

            # Support "Rs. 300 application fee" without picking up a preceding
            # admission-fee amount or unrelated clause.
            left_start = labels[index - 1].end() if index else 0
            left = section[left_start:label.start()]
            amounts = list(_MONEY.finditer(left))
            if amounts:
                previous = amounts[-1]
                between = left[previous.end():]
                if (
                    len(between) <= 25
                    and re.fullmatch(r"[\s,()\-]*(?:as\s+(?:the\s+)?)?", between, re.I)
                    and not _NEGATED.search(right[:40])
                ):
                    quote = section[left_start + previous.start():min(end, label.end() + 100)]
                    yield quote.strip(" ,:-"), previous.group(0).strip()


def labeled_fee_evidence(record, kind):
    """Find distinct quoted passages for a particular fee kind.

    Prefer original OCR/PDF text over model-generated structured fields.
    An unlabeled fees.amount is *never* promoted into an application fee.
    """
    sd = record.get("structured_data") or {}
    text_sources = [record.get("raw_text")]
    text_sources.extend(sd.get("key_points") or [])
    text_sources.append(sd.get("action_required"))
    results = []
    seen = set()
    for text in text_sources:
        for quote, amount in _directly_labeled_fee(text, kind):
            key = (amount.casefold(), " ".join(quote.casefold().split()))
            if key not in seen:
                seen.add(key)
                results.append((quote, amount))
        if results:
            # Use the strongest source that provides direct, typed fee evidence.
            return results[:5]
    return []
