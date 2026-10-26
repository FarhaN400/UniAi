"""Offline regression checks for high-priority fixes #5, #7 and #8.

Use: PYTHONPATH=backend python -m unittest discover -s backend/tests -p 'test_high_priority_batch.py' -v
"""
import ast
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from notice_dates import official_issue_date
from review_workflow import approval_update, rejection_update, review_warnings
from test_academic_scope import notice, import_retrieve_offline


class OfficialIssueDateTests(unittest.TestCase):
    def test_never_infer_official_date_from_detected_at(self):
        today = datetime.now(timezone.utc)
        record = {"structured_data": {"issue_date": None}, "detected_at": today}
        self.assertIsNone(official_issue_date(record))

    def test_invalid_date_does_not_fall_back(self):
        record = {"structured_data": {"issue_date": "31-02-2026"},
                  "detected_at": datetime.now(timezone.utc)}
        self.assertIsNone(official_issue_date(record))

    def test_formats_supported(self):
        cases = [
            "26-10-2026", "26/10/2026", "26.10.2026", "2026-10-26",
            "2026/10/26", "26 October 2026", "October 26, 2026",
            "2026-10-26T09:14:00Z", "26-10-2026 09:14",
        ]
        for value in cases:
            with self.subTest(value=value):
                self.assertEqual(
                    official_issue_date({"structured_data": {"issue_date": value}}),
                    date(2026, 10, 26))

    def test_unknown_timestamp_does_not_claim_today(self):
        self.assertIsNone(official_issue_date({
            "structured_data": {}, "detected_at": datetime.now(timezone.utc)
        }))

    def test_real_date_objects_are_valid(self):
        self.assertEqual(
            official_issue_date({"structured_data": {"issue_date": date(2025, 9, 8)}}),
            date(2025, 9, 8)
        )


class RetrievalDateTests(unittest.TestCase):
    def test_detected_today_is_not_published_today(self):
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        old = notice("undated", "Notice without a publication date", issue_date=None)
        old["detected_at"] = datetime.now(timezone.utc)
        issued = notice("issued", "Notice with today's issue date",
                        issue_date=today.strftime("%d-%m-%Y"))
        issued["detected_at"] = datetime.now(timezone.utc) - timedelta(days=3)
        retrieval = import_retrieve_offline([old, issued])
        ids = [r["notice_id"] for r in retrieval.retrieve_time_based(
            "notices published today", top_k=10)]
        self.assertEqual(ids, ["issued"])

    def test_yesterday_uses_issue_date_not_discovery_date(self):
        yesterday = datetime.now(ZoneInfo("Asia/Kolkata")).date() - timedelta(days=1)
        old = notice("undated", "Notice without issue date", issue_date=None)
        old["detected_at"] = datetime.now(timezone.utc) - timedelta(days=1)
        issued = notice("issued", "Notice issued yesterday",
                        issue_date=yesterday.strftime("%d-%m-%Y"))
        issued["detected_at"] = datetime.now(timezone.utc)
        retrieval = import_retrieve_offline([old, issued])
        ids = [r["notice_id"] for r in retrieval.retrieve_time_based(
            "notices published yesterday", top_k=10)]
        self.assertEqual(ids, ["issued"])

    def test_exact_date_filters_missing_or_invalid_issued_dates(self):
        published = notice("issued", "MAKAUT general circular", issue_date="26-10-2026")
        undated = notice("undated", "MAKAUT general circular", issue_date=None)
        undated["detected_at"] = datetime(2026, 10, 26, tzinfo=timezone.utc)
        bad = notice("invalid", "MAKAUT general circular", issue_date="31-02-2026")
        bad["detected_at"] = datetime(2026, 10, 26, tzinfo=timezone.utc)
        retrieval = import_retrieve_offline([published, undated, bad])
        results = retrieval.retrieve_filtered_notices(
            "Notices issued on 26 October 2026", top_k=10
        )
        self.assertEqual([r["notice_id"] for r in results], ["issued"])


class LongReviewTests(unittest.TestCase):
    def setUp(self):
        self.notice = {
            "status": "review_required", "quality_review_required": True,
            "raw_text": "A complete PDF scan", "requires_chunking": True,
            "chunk_extractions": [{"title": "Important notice"}],
            "structured_data": {"title": "Important notice", "key_points": []},
        }

    def test_review_requires_reviewer_and_notes(self):
        with self.assertRaises(ValueError):
            approval_update(self.notice, "", "Checked PDF against all pages")
        with self.assertRaises(ValueError):
            approval_update(self.notice, "Staff", "ok")

    def test_approval_makes_document_eligible_for_index(self):
        updates = approval_update(
            self.notice, "Staff Reviewer", "Checked all pages against original PDF"
        )["$set"]
        self.assertEqual(updates["status"], "processed")
        self.assertFalse(updates["quality_review_required"])
        self.assertFalse(updates["pinecone_indexed"])
        self.assertTrue(updates["review_approved_at"].tzinfo is not None)

    def test_conflicting_merge_requires_explicit_acknowledgement(self):
        self.notice["structured_data"]["key_points"] = [
            "Extracted last_date candidates requiring verification: 1, 2."
        ]
        self.assertTrue(review_warnings(self.notice))
        with self.assertRaises(ValueError):
            approval_update(
                self.notice, "Reviewer", "Checked the PDF against extraction"
            )
        update = approval_update(
            self.notice, "Reviewer", "Resolved discrepancy in source PDF",
            acknowledge_warnings=True,
        )
        self.assertEqual(len(update["$set"]["review_acknowledged_warnings"]), 1)

    def test_empty_raw_text_cannot_be_approved_even_with_override(self):
        self.notice["raw_text"] = ""
        with self.assertRaises(ValueError):
            approval_update(self.notice, "Reviewer", "Checked source document thoroughly",
                            acknowledge_warnings=True)

    def test_already_processed_is_not_approvable(self):
        self.notice["status"] = "processed"
        with self.assertRaises(ValueError):
            approval_update(self.notice, "Reviewer", "Checked source document thoroughly")

    def test_rejection_remains_out_of_search_index(self):
        update = rejection_update(self.notice, "Reviewer", "Not consistent with original PDF")
        self.assertEqual(update["$set"]["status"], "review_rejected")
        self.assertTrue(update["$set"]["quality_review_required"])
        self.assertFalse(update["$set"]["pinecone_indexed"])


def _load_safe_grounded_answer():
    """Compile the real function in isolation without importing cloud dependencies."""
    module_file = Path(__file__).resolve().parents[1] / "Module4" / "main.py"
    tree = ast.parse(module_file.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
              and n.name == "_safe_grounded_answer")
    namespace = {}
    compiled = compile(ast.Module(body=[fn], type_ignores=[]), str(module_file), "exec")
    exec(compiled, namespace)
    return namespace


class _FakeState:
    def __init__(self):
        self.turns = []
        self.last = [{"notice_id": "previous"}]

    def get_last_notice_records(self):
        return self.last

    def set_last_results(self, records):
        self.last = list(records)


class GroundedFallbackTests(unittest.TestCase):
    def setUp(self):
        self.ns = _load_safe_grounded_answer()
        self.ns["NO_RESULTS_MESSAGE"] = "I could not find this information in the available university notices."
        self.ns["_no_matches"] = lambda question: "No matching notice."
        self.record = {"notice_id": "one", "title": "Notice without requested details"}

    def test_no_evidence_does_not_turn_into_summary_or_attach_pdf(self):
        calls = []
        self.ns["answer_from_records"] = lambda *args, **kwargs: self.ns["NO_RESULTS_MESSAGE"]
        self.ns["_save_reply"] = lambda *args, **kwargs: calls.append((args, kwargs))
        answer = self.ns["_safe_grounded_answer"]("What is the application fee?", [self.record], _FakeState())
        self.assertEqual(answer, self.ns["NO_RESULTS_MESSAGE"])
        self.assertEqual(calls, [])

    def test_provider_error_returns_temporarily_unavailable_without_sources(self):
        calls = []
        def throw(*args, **kwargs):
            raise TimeoutError("model timed out")
        self.ns["answer_from_records"] = throw
        self.ns["_save_reply"] = lambda *args, **kwargs: (calls.append((args, kwargs)), args[2])[1]
        answer = self.ns["_safe_grounded_answer"]("What is the fee?", [self.record], _FakeState())
        self.assertIn("temporarily unavailable", answer)
        self.assertEqual(calls[0][1]["records"], [])
        self.assertNotIn("Notice without requested details", answer)

    def test_no_record_path_has_no_pdfs(self):
        calls = []
        self.ns["_save_reply"] = lambda *args, **kwargs: (calls.append((args, kwargs)), args[2])[1]
        answer = self.ns["_safe_grounded_answer"]("Unknown notice?", [], _FakeState())
        self.assertEqual(answer, "No matching notice.")
        self.assertEqual(calls[0][1]["records"], [])


if __name__ == "__main__":
    unittest.main()
