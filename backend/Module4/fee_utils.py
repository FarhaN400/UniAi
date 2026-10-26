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
    """Return a single explicitly requested category (or None for comparisons)."""
    query = str(question or "")
    # Direct labels take precedence over phrases such as "fee for admission".
    # In "application fee for admission", the requested payment is application.
    explicit = (
        ("application", r"\bapplication[\s-]*fees?\b"),
        ("admission", r"\badmission[\s-]*fees?\b"),
        ("registration", r"\bregistration[\s-]*fees?\b"),
        ("examination", r"\b(?:exam|examination)[\s-]*fees?\b"),
        ("tuition", r"\btuition[\s-]*fees?\b"),
        ("processing", r"\bprocessing[\s-]*fees?\b"),
        ("counselling", r"\b(?:counselling|counseling)[\s-]*fees?\b"),
    )
    matches = [kind for kind, pattern in explicit if re.search(pattern, query, re.I)]
    if matches:
        return matches[0] if len(matches) == 1 else None
    if re.search(r"\bfees?\s+for\s+(?:an?\s+)?application\b", query, re.I):
        return "application"
    if re.search(r"\bfees?\s+for\s+admission\b", query, re.I):
        return "admission"
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
    text_sources = [(record.get("raw_text"), False)]
    text_sources.extend((point, True) for point in (sd.get("key_points") or []))
    text_sources.append((sd.get("action_required"), True))
    results = []
    seen = set()
    for text, extracted in text_sources:
        if extracted and re.search(r"\brequir(?:es?|ing)\s+verification\b", str(text or ""), re.I):
            # Merged chunks explicitly flagged these values as unverified.
            continue
        for quote, amount in _directly_labeled_fee(text, kind):
            key = (amount.casefold(), " ".join(quote.casefold().split()))
            if key not in seen:
                seen.add(key)
                results.append((quote, amount))
        if results:
            # Use the strongest source that provides direct, typed fee evidence.
            return results[:5]
    return []


def answer_fee_question(question, record, source, title):
    """Provide a cautious, source-linked answer for fee questions.

    The exact category requested must have directly labelled fee evidence.
    Legacy/untyped extraction amounts only support generic fee responses.
    """
    sd = record.get("structured_data") or {}
    kind = query_fee_kind(question)
    fees = sd.get("fees") or {}
    if kind:
        # The generic fees.amount (including legacy records) does not
        # identify a fee category. Require an explicit label and amount in
        # this notice's own OCR or extracted evidence.
        matches = labeled_fee_evidence(record, kind)
        if matches:
            lines = list(dict.fromkeys(quote for quote, _ in matches))
            return (f"{kind.capitalize()}-fee evidence from '{title}':\n"
                    + "\n".join(f"- {line}" for line in lines)
                    + f"\n{source}")
        article = "an" if kind in ("application", "admission", "examination") else "a"
        return (f"I cannot verify {article} {kind}-fee amount from the available "
                f"extracted details of '{title}'. A different fee type does "
                f"not establish this amount. Check the original PDF.\n{source}")

    # General fee questions may refer to any payment category. Prefer a
    # directly labelled excerpt over an ambiguously typed legacy amount.
    evidence = []
    for fee_kind in ("application", "admission", "registration", "examination",
                     "tuition", "processing", "counselling"):
        for quote, _ in labeled_fee_evidence(record, fee_kind):
            if quote not in evidence:
                evidence.append(quote)
    if evidence:
        return (f"Fee information stated in '{title}':\n"
                + "\n".join(f"- {line}" for line in evidence[:6])
                + f"\n{source}")

    amount = fees.get("amount") if isinstance(fees, dict) else None
    currency = fees.get("currency") if isinstance(fees, dict) else None
    fee_type = fees.get("type") if isinstance(fees, dict) else None
    if amount not in (None, "", "null", "None"):
        label = f"{fee_type.capitalize()} fee" if fee_type in (
            "application", "admission", "registration", "examination",
            "tuition", "processing", "counselling", "other"
        ) else "Fee (category not verified)"
        return (f"{label} in the extracted record: "
                f"{str(amount)} {str(currency or '')}. "
                f"Confirm the category and amount in the original PDF.\n{source}")
    return f"I cannot verify a fee amount from the extracted notice details.\n{source}"
