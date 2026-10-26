"""Parse a notice's official issue date without fabricating a publication date.

Scrape/detection timestamps are operational metadata; they are never used as
evidence that the university issued a notice today or yesterday.
"""
from datetime import date, datetime
import re

_FORMATS = (
    "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d",
    "%Y/%m/%d", "%Y.%m.%d", "%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M",
    "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y",
)


def official_issue_date(record):
    """Return a date only when the extracted notice supplies a valid date."""
    structured = record.get("structured_data") or {}
    value = structured.get("issue_date")
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    text = " ".join(value.strip().split())
    if not text or text.lower() in ("none", "null", "n/a", "unknown"):
        return None
    for fmt in _FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    # ISO datetime may have Z or a timezone offset. Its calendar date is
    # retained as explicitly written, not converted from discovery time.
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?", text, re.I):
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None
