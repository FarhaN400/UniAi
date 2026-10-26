"""Deterministic academic-session and year-identity matching for notices.

Calendar publication years, entrance-exam years, and academic sessions are
different facts. This module has no DB/API dependencies so it can be tested
offline before a notice is allowed into RAG context.
"""
import re


_SESSION_PATTERN = re.compile(
    r"(?<!\d)(20\d{2})\s*[-–—/]\s*(20\d{2}|\d{2})(?!\d)"
)
_YEAR_PATTERN = re.compile(r"(?<!\d)20\d{2}(?!\d)")


def academic_sessions(value):
    """Return explicitly written (start_year, end_year) academic-year pairs.

    Treat 2026-27, 2026–2027, and 2026/27 identically. A date such as
    2026/10/26 is not a session.
    """
    text = str(value or "")
    result = []
    for match in _SESSION_PATTERN.finditer(text):
        start = int(match.group(1))
        suffix = match.group(2)
        end = int(suffix) if len(suffix) == 4 else (start // 100) * 100 + int(suffix)
        if len(suffix) == 2 and end <= start:
            end += 100
        # Conventional annual academic sessions; reject incidental number
        # ranges and partial calendar dates.
        if end != start + 1:
            continue
        pair = (start, end)
        if pair not in result:
            result.append(pair)
    return result


def requested_session(question, *, force_year=None):
    """Return an unambiguous requested session.

    For comparisons of 2025-26 with 2026-27, the caller can set
    force_year=2025 or 2026 to resolve one side at a time.
    """
    sessions = academic_sessions(question)
    if force_year is not None:
        candidates = [pair for pair in sessions if pair[0] == int(force_year)]
        return candidates[0] if len(candidates) == 1 else None
    return sessions[0] if len(sessions) == 1 else None


def _session_sources(record):
    """Check authoritative notice identity before descriptive OCR summaries."""
    data = record.get("structured_data") or {}
    for value in (
        record.get("title"),
        data.get("academic_session"),
        data.get("academic_year"),
        data.get("title"),
    ):
        sessions = academic_sessions(value)
        if sessions:
            return sessions

    # Descriptions are less reliable than title/session metadata. If they
    # mention multiple historical sessions, do not guess which is the target.
    for value in (
        data.get("target_audience"),
        data.get("summary"),
        data.get("key_points"),
        str(record.get("raw_text") or "")[:4000],
    ):
        sessions = academic_sessions(value)
        if sessions:
            return sessions if len(sessions) == 1 else []
    return []


def matches_session(record, session):
    """Fail closed: issue_date or detected_at cannot prove an academic session."""
    if session is None:
        return True
    return session in _session_sources(record)


def _standalone_years(text):
    """Exclude years embedded inside session ranges from individual year IDs."""
    text = str(text or "")
    spans = [m.span() for m in _SESSION_PATTERN.finditer(text)]
    years = set()
    for match in _YEAR_PATTERN.finditer(text):
        if not any(left <= match.start() and match.end() <= right for left, right in spans):
            years.add(int(match.group(0)))
    return years


def matches_identity_year(record, year):
    """Match an entrance-exam year or a *starting* academic-session year.

    For the title 'WBJEEB-2026 allotted students, session 2025-26',
    the standalone exam year is 2026. But a title containing only
    'Academic session 2025-26' has identity year 2025, not 2026.
    """
    if year is None:
        return True
    year = int(year)
    data = record.get("structured_data") or {}
    for value in (
        record.get("title"), data.get("title"),
        data.get("academic_session"), data.get("academic_year"),
    ):
        if not value:
            continue
        standalone = _standalone_years(value)
        if standalone:
            return year in standalone
        sessions = academic_sessions(value)
        if sessions:
            return year in {start for start, _ in sessions}
    for value in (data.get("target_audience"), data.get("summary"), data.get("key_points")):
        if not value:
            continue
        standalone = _standalone_years(value)
        if standalone:
            return year in standalone
        sessions = academic_sessions(value)
        if sessions:
            return year in {start for start, _ in sessions}

    # Last resort: explicit notice issue date (NOT a scraper timestamp).
    issue = data.get("issue_date")
    if issue:
        years = _standalone_years(issue)
        if years:
            return year in years
    return False
