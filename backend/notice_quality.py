"""Display-time guards for inconsistent historical OCR/LLM extractions.

Do not silently change a university's official facts or infer the 'correct'
date. Suppress a demonstrably suspect extracted summary until a reviewer
checks the original PDF. Existing MongoDB data is intentionally unchanged.
"""
import re


def summary_warning(record):
    sd = record.get("structured_data") or {}
    title = str(sd.get("title") or record.get("title") or "")
    summary = str(sd.get("summary") or "")
    identity = re.search(
        r"\b(?:WBJEEB?|JELET|JECA|PGET|CET|JEMAT)[-\s]*(20\d{2})\b",
        title, re.I,
    )
    if not identity or not summary:
        return None
    target_year = int(identity.group(1))
    if not re.search(r"\b(?:reporting|allotted|admission)\b", summary, re.I):
        return None
    # Only flag an earlier event year for admissions/reporting. A notice may
    # legitimately mention its previous circular number or an older policy;
    # those references do not by themselves invalidate a summary.
    dated_event = re.search(
        r"\b(?:report(?:ing)?|admission)\s+(?:dates?|on|from|between|during)\b"
        r"([\s\S]{0,220})", summary, re.I
    )
    # A lead-in can identify JELET-2025 before giving 'Oct 2024'.
    # Examine every date year in the relevant reporting passage, not just
    # the first mentioned year.
    years = [int(y) for y in re.findall(r"(?<!\d)(20\d{2})(?!\d)",
                                        dated_event.group(1))] if dated_event else []
    if any(year < target_year for year in years):
        return ("The extracted admission/reporting dates appear to precede "
                "the entrance-exam year. Summary withheld until the official "
                "PDF is reviewed.")
    return None


def display_summary(record):
    warning = summary_warning(record)
    if warning:
        return None, warning
    return (record.get("structured_data") or {}).get("summary"), None
