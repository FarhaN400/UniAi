"""Explicit human review workflow for long, potentially incomplete OCR notices.

The review queue is deliberately NOT searchable until a reviewer checks the
original PDF and approves the structured extraction. This module validates
the transition without contacting MongoDB or Pinecone.
"""
from datetime import datetime, timezone
import re


def review_warnings(notice):
    """Return unresolved warnings; reviewing must not silently erase them."""
    data = notice.get("structured_data") or {}
    warnings = []
    for point in data.get("key_points") or []:
        text = str(point).strip()
        if re.search(r"\brequir(?:ing|es?)\s+verification\b", text, re.I):
            warnings.append(text)
    if not notice.get("raw_text"):
        warnings.append("Missing PDF text (raw_text)")
    if not isinstance(data, dict) or not data.get("title"):
        warnings.append("Missing extracted notice title")
    if notice.get("requires_chunking") and not notice.get("chunk_extractions"):
        warnings.append("Missing saved per-chunk extractions")
    return warnings


def approval_update(notice, reviewer, notes, *, acknowledge_warnings=False):
    """Prepare approval only for a deliberate human review of one queue item."""
    if notice.get("status") != "review_required" or notice.get("quality_review_required") is not True:
        raise ValueError("Only notices currently pending manual review may be approved")
    reviewer = str(reviewer or "").strip()
    notes = str(notes or "").strip()
    if not reviewer or len(reviewer) < 2:
        raise ValueError("Reviewer name is required")
    if len(notes) < 12:
        raise ValueError("At least 12 characters of review notes are required")
    warnings = review_warnings(notice)
    if warnings and not acknowledge_warnings:
        raise ValueError("Unresolved review warnings: " + "; ".join(warnings[:5]))
    if not isinstance(notice.get("structured_data"), dict) or not notice["structured_data"].get("title"):
        raise ValueError("Structured title is required even when warnings are acknowledged")
    if not str(notice.get("raw_text") or "").strip():
        raise ValueError("Extracted PDF text is required even when warnings are acknowledged")
    return {
        "$set": {
            "status": "processed",
            "quality_review_required": False,
            "pinecone_indexed": False,
            "review_approved_at": datetime.now(timezone.utc),
            "review_approved_by": reviewer,
            "review_notes": notes,
            "review_acknowledged_warnings": warnings if acknowledge_warnings else [],
        }
    }


def rejection_update(notice, reviewer, notes):
    if notice.get("status") != "review_required":
        raise ValueError("Only notices pending review may be rejected")
    if len(str(reviewer or "").strip()) < 2 or len(str(notes or "").strip()) < 12:
        raise ValueError("Reviewer and detailed rejection notes are required")
    return {
        "$set": {
            "status": "review_rejected",
            "quality_review_required": True,
            "review_rejected_at": datetime.now(timezone.utc),
            "review_approved_by": str(reviewer).strip(),
            "review_notes": str(notes).strip(),
            "pinecone_indexed": False,
        }
    }
