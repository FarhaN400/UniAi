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
    # Require a concrete calendar date next to an earlier year. A historical
    # circular reference in a summary is not by itself an invalid deadline.
    # Includes PDF hyphens like '13‑15 Oct 2024' seen in live JELET output.
    year_in_event_dates = [
        int(y) for y in re.findall(
            r"\b\d{1,2}(?:\s*[-–‑—]\s*\d{1,2})?\s+"
            r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|"
            r"May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|"
            r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(20\d{2})\b",
            summary, re.I,
        )
    ]
    year_in_event_dates.extend(
        int(y) for y in re.findall(
            r"\b\d{1,2}[-/]\d{1,2}[-/](20\d{2})\b", summary
        )
    )
    if any(year < target_year for year in year_in_event_dates):
        return ("The extracted admission/reporting dates appear to precede "
                "the entrance-exam year. Summary withheld until the official "
                "PDF is reviewed.")
    return None


def display_summary(record):
    warning = summary_warning(record)
    if warning:
        return None, warning
    return (record.get("structured_data") or {}).get("summary"), None
