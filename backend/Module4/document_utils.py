"""Evidence-first document-list answers for MAKAUT notices.

Never treat the word "verification" alone as evidence that the requested
documents have been identified. Preserve the official OCR's wording and its
original/photocopy qualifications instead of inventing a standard checklist.
"""
import re


_DOCUMENT_NAME = re.compile(
    r"\b(?:"
    r"(?:class|standard|std\.?)\s*(?:10|12|xii?|x)\s*(?:th)?\s*"
    r"(?:mark[\s-]*sheets?|certificates?|pass[\s-]*certificates?)|"
    r"(?:10th|12th|x|xii)\s*(?:mark[\s-]*sheets?|certificates?)|"
    r"mark[\s-]*sheets?|"
    r"(?:admit|allotment|rank|score|identity|registration|migration|transfer|"
    r"character|bonafide|school[\s-]*leaving)\s*(?:cards?|letters?|certificates?)|"
    r"(?:wbjee|wbjeeb|jelet|jeca)\s*(?:rank|score|admit|allotment)\s*(?:cards?|letters?)|"
    r"(?:aadhaar|aadhar|adhar)(?:\s*cards?)?|"
    r"(?:pan|voter)\s*(?:id|cards?)|"
    r"(?:birth|domicile|residence|residential|caste|category|community|"
    r"income|ews|obc|sc|st|pwd|disability|medical|nationality|"
    r"migration|transfer|character|conduct|degree|graduation|"
    r"school[\s-]*leaving|eligibility)\s*(?:certificates?|proof)|"
    r"certificates?\s+of\s+[a-z][a-z\s-]{2,50}|"
    r"(?:proof|evidence)\s+of\s+(?:identity|address|residence|age|dob|birth)|"
    r"(?:passport[\s-]*size[d]?\s*)?(?:photographs?|photos?)(?:\s*\(\s*passport\s*size\s*\))?|"
    r"(?:passport[\s-]*size[d]?\s*photographs?)|"
    r"(?:application|admission|registration)\s*(?:forms?|printouts?|receipts?)|"
    r"(?:fee|payment|transaction)\s*(?:receipts?|challans?)|"
    r"(?:anti[\s-]*ragging|medical|gap)\s*(?:affidavits?|declarations?)"
    r")\b",
    re.IGNORECASE,
)
_LIST_HEADING = re.compile(
    r"\b(?:"
    r"(?:list\s+of|following|required|necessary|mandatory|original|supporting)\s+"
    r"(?:documents?|certificates?)|"
    r"documents?\s+(?:required|needed|to\s+be\s+(?:produced|submitted)|"
    r"for\s+(?:physical\s+)?verification)|"
    r"certificates?\s+to\s+be\s+(?:produced|submitted)|"
    r"bring\s+(?:the\s+)?(?:following|original)\s+documents?"
    r")\b",
    re.IGNORECASE,
)
_REQUIREMENT = re.compile(
    r"\b(?:bring|carry|submit|provide|produce|upload|attach|enclose|present|"
    r"furnish|show|required|mandatory|need\s+to|must\s+bring|must\s+submit|"
    r"self[\s-]*attested|photocopies?|xerox|originals?)\b",
    re.IGNORECASE,
)
_NOT_REQUIRED = re.compile(
    r"\b(?:not\s+(?:required|needed|necessary|to\s+be\s+(?:submitted|produced|"
    r"carried|brought))|no\s+need\s+to|need\s+not|do\s+not\s+"
    r"(?:bring|submit|provide|produce|upload|carry)|not\s+accepted|"
    r"no\s+[\w\s-]{1,55}?\s+(?:is\s+)?required)\b",
    re.IGNORECASE,
)
_COPY_INSTRUCTIONS = re.compile(
    r"\b(?:self[\s-]*attest(?:ed|ed)?|attested|photocop(?:y|ies)|xerox|"
    r"originals?\s+(?:and|with|for)|copies\s+of\s+(?:the|all|each))\b",
    re.IGNORECASE,
)
_ENUMERATED = re.compile(
    r"^\s*(?:[-*•]\s+|\(?\d{1,2}\)?[.)]\s+|\(?[ivxlcdm]{1,6}\)[.)]?\s+)",
    re.IGNORECASE,
)


def _lines(text):
    for line in str(text or "").splitlines():
        line = " ".join(line.split())
        if line:
            yield line


def _join_wrapped_lines(raw_text):
    """Join OCR's hard-wrapped checklist entries before extracting named documents.

    PDF extraction frequently splits "original Mark sheet of Class 10" from
    "and 12, Admit Card, Rank Card, ..." on the next physical line.
    Keep headings/numbered entries/sentences separate; cap groups to avoid
    accidentally copying other sections of a long PDF.
    """
    grouped, current = [], ""
    for raw_line in str(raw_text or "")[:180000].splitlines():
        line = " ".join(raw_line.split())
        if not line:
            if current:
                grouped.append(current)
                current = ""
            continue
        starts_new = bool(_ENUMERATED.match(line) or _LIST_HEADING.search(line))
        ended = bool(re.search(r"[.!?:]\s*$", current))
        if (current and not starts_new and not ended
                and len(current) + len(line) < 1400):
            current += " " + line
        else:
            if current:
                grouped.append(current)
            current = line
    if current:
        grouped.append(current)
    return grouped


def _clauses(line):
    """Break distinct instructions apart; never combine prohibited and required."""
    # Semicolons and a completed sentence are safe boundaries. Avoid splitting
    # periods in "Mr."/"No." and the periods of numbered list prefixes.
    for portion in re.split(r";+\s*|(?<=[.!?])\s+(?=[A-Z])", line):
        portion = portion.strip()
        if portion:
            yield portion


def _extract_named_lines(raw_text):
    """Extract original OCR passages actually naming required documents."""
    lines = _join_wrapped_lines(raw_text)
    found, notes, seen, notes_seen = [], [], set(), set()
    scope_until = -1
    last_list_entry = -1
    for i, line in enumerate(lines):
        is_heading = bool(
            _LIST_HEADING.search(line)
            or re.fullmatch(r"(?:document|documents|physical)\s+verification\s*:?", line, re.I)
        )
        if is_heading:
            scope_until = i + 60
            last_list_entry = i
        elif i - last_list_entry > 4:
            # Do not pull a later, unrelated section into the document list.
            scope_until = -1

        for part in _clauses(line):
            if _NOT_REQUIRED.search(part):
                continue
            has_named_document = bool(_DOCUMENT_NAME.search(part))
            in_document_list = i <= scope_until
            has_requirement = bool(_REQUIREMENT.search(part) or _LIST_HEADING.search(part))
            # A random reference to an application form or mark-sheet in an
            # eligibility paragraph does not establish a required document.
            if has_named_document and (in_document_list or has_requirement):
                if in_document_list:
                    last_list_entry = i
                key = re.sub(r"\W+", " ", part).strip().casefold()
                if key and key not in seen:
                    seen.add(key)
                    found.append(part[:1200])
            elif (in_document_list and _COPY_INSTRUCTIONS.search(part)
                  and _REQUIREMENT.search(part)):
                key = re.sub(r"\W+", " ", part).strip().casefold()
                if key and key not in notes_seen:
                    notes_seen.add(key)
                    notes.append(part[:400])
    return found[:25], notes[:5]


def _structured_document_fallback(sd):
    """Use extracted document names only when original OCR is unavailable."""
    found, seen = [], set()
    explicit = sd.get("required_documents") or []
    if isinstance(explicit, str):
        explicit = [explicit]
    for entry in explicit:
        value = " ".join(str(entry or "").split())
        if value and _DOCUMENT_NAME.search(value) and not _NOT_REQUIRED.search(value):
            key = re.sub(r"\W+", " ", value).strip().casefold()
            if key not in seen:
                found.append(value[:550])
                seen.add(key)
    if found:
        return found[:25]

    for entry in sd.get("key_points") or []:
        value = " ".join(str(entry or "").split())
        if (_DOCUMENT_NAME.search(value) and
                (_REQUIREMENT.search(value) or _LIST_HEADING.search(value)) and
                not _NOT_REQUIRED.search(value)):
            key = re.sub(r"\W+", " ", value).strip().casefold()
            if key not in seen:
                found.append(value[:550])
                seen.add(key)
    action = " ".join(str(sd.get("action_required") or "").split())
    if (_DOCUMENT_NAME.search(action) and
            (_REQUIREMENT.search(action) or _LIST_HEADING.search(action)) and
            not _NOT_REQUIRED.search(action)):
        key = re.sub(r"\W+", " ", action).strip().casefold()
        if key not in seen:
            found.append(action[:550])
    return found[:25]


def answer_document_question(record, title, source, question=None):
    """Return a grounded, source-linked list, or an explicit uncertainty answer.

    Prefer source PDF OCR, including names absent from old structured JSON.
    Structured extraction is only a fallback when the raw text is unavailable;
    it is then labelled as extracted, not verified against the original PDF.
    """
    sd = record.get("structured_data") or {}
    raw = str(record.get("raw_text") or "")
    if raw.strip():
        documents, instructions = _extract_named_lines(raw)
        if documents:
            # When the student asks about ONE named document, show its exact
            # excerpt and qualifiers rather than burying it in a large list.
            # Avoid a universal yes/no answer across different admission rounds.
            q = str(question or "").casefold()
            sought = None
            if re.search(r"\bdomicile\b", q):
                sought = r"\b(?:domicile|residen(?:ce|tial))\b"
            elif re.search(r"\b(?:self[- ]?attested|photocop(?:y|ies)|xerox)\b", q):
                sought = r"\b(?:self[- ]?attested|photocop(?:y|ies)|xerox)\b"
            elif re.search(r"\b(?:class\s*10|class\s*12|marksheets?|mark\s*sheets?)\b", q):
                sought = r"\b(?:mark[\s-]*sheets?|class\s*10|class\s*12)\b"
            selected = documents
            if sought:
                matches = [item for item in [*documents, *instructions]
                           if re.search(sought, item, re.I)]
                if not matches:
                    return (f"I couldn't verify that specific document "
                            f"requirement from the available extracted text of "
                            f"'{title}'. Please check the original notice.\n{source}")
                selected = list(dict.fromkeys(matches))[:8]
            output = [
                f"Document requirements found in the extracted PDF text for '{title}':",
                *(f"- {item}" for item in selected),
            ]
            if instructions:
                output.append("Additional instructions from the same PDF:")
                output.extend(f"- {item}" for item in instructions)
            output.append(f"This is based on extracted PDF text; confirm the full list in the official notice.\n{source}")
            return "\n".join(output)
        return (
            f"I couldn't verify a list of required documents from the "
            f"available PDF text for '{title}'. Generic document-verification "
            f"instructions do not establish which documents to bring. "
            f"Please check the official notice.\n{source}"
        )

    documents = _structured_document_fallback(sd)
    if documents:
        return (
            f"Documents named in the extracted record for '{title}' "
            f"(not cross-checked against the PDF text):\n"
            + "\n".join(f"- {item}" for item in documents)
            + f"\nPlease confirm them in the official notice.\n{source}"
        )
    return (
        f"I couldn't verify a list of required documents from the "
        f"available extracted details of '{title}'. "
        f"Please consult the official PDF.\n{source}"
    )
