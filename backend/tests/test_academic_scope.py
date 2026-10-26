"""Academic-session/notice-year regression tests (offline; no API keys).

Run from repository root:
PYTHONPATH=backend python -m unittest discover -s backend/tests -p 'test_academic_scope.py' -v
"""
import importlib.util
import sys
import types
import unittest
from pathlib import Path

from academic_scope import (
    academic_sessions, requested_session, matches_session,
    matches_identity_year,
)


def notice(notice_id, title, issue_date="05-10-2026", *, summary="", audience="Students",
           extracted_title=None, raw_text="", academic_year=None):
    sd = {
        "title": extracted_title if extracted_title is not None else title,
        "issue_date": issue_date,
        "target_audience": audience,
        "summary": summary,
        "key_points": [],
        "notice_type": "Admission",
        "academic_year": academic_year,
    }
    return {"notice_id": notice_id, "title": title, "status": "processed",
            "structured_data": sd, "raw_text": raw_text,
            "url": f"https://makautwb.ac.in/{notice_id}.pdf"}


class SessionParsingTests(unittest.TestCase):
    def test_full_and_short_end_year_equivalent(self):
        self.assertEqual(academic_sessions("AY 2026-27"), [(2026, 2027)])
        self.assertEqual(academic_sessions("academic session 2026-2027"), [(2026, 2027)])

    def test_unicode_dashes_and_spaces(self):
        for sep in ("–", "—", "/", " - "):
            with self.subTest(sep=sep):
                self.assertEqual(academic_sessions(f"2026{sep}27"), [(2026, 2027)])

    def test_calendar_date_is_not_a_session(self):
        self.assertEqual(academic_sessions("issued 2026/10/26"), [])
        self.assertEqual(academic_sessions("date 2026-10-26"), [])

    def test_nonconsecutive_years_are_not_assumed_academic_session(self):
        self.assertEqual(academic_sessions("2025-2027"), [])

    def test_order_and_deduplication(self):
        self.assertEqual(academic_sessions("2025-26 and 2026-27 and 2025-2026"),
                         [(2025, 2026), (2026, 2027)])

    def test_comparison_without_force_year_has_no_single_session(self):
        self.assertIsNone(requested_session("Compare 2025-26 and 2026-27"))

    def test_comparison_force_year_scopes_its_own_session(self):
        q = "Compare academic session 2025-26 and 2026-27"
        self.assertEqual(requested_session(q, force_year=2025), (2025, 2026))
        self.assertEqual(requested_session(q, force_year=2026), (2026, 2027))
        self.assertIsNone(requested_session(q, force_year=2027))


class SessionIdentityTests(unittest.TestCase):
    def setUp(self):
        self.old = notice("old", "Registration of Students for Academic Session 2025-2026")
        self.new = notice("new", "Registration of Students for Academic Session 2026-27")
        self.exam = notice("exam", "WBJEEB-2026 allotted students, session 2025-26")
        self.issue_only = notice("issue", "Notice on document verification",
                                 issue_date="11-10-2026")

    def test_exact_session_match(self):
        self.assertTrue(matches_session(self.new, (2026, 2027)))
        self.assertFalse(matches_session(self.old, (2026, 2027)))

    def test_old_session_end_year_not_identity_year(self):
        self.assertFalse(matches_identity_year(self.old, 2026))
        self.assertTrue(matches_identity_year(self.old, 2025))
        self.assertFalse(matches_identity_year(self.new, 2027))
        self.assertTrue(matches_identity_year(self.new, 2026))

    def test_exam_year_can_differ_from_academic_session(self):
        self.assertTrue(matches_identity_year(self.exam, 2026))
        self.assertTrue(matches_session(self.exam, (2025, 2026)))
        self.assertFalse(matches_session(self.exam, (2026, 2027)))

    def test_issue_year_does_not_establish_session(self):
        self.assertFalse(matches_session(self.issue_only, (2026, 2027)))
        self.assertTrue(matches_identity_year(self.issue_only, 2026))

    def test_source_title_beats_inconsistent_extracted_title(self):
        rec = notice("conflict",
                     "Registration of Students for Academic Session 2025-26",
                     extracted_title="Registration of Students for Academic Session 2026-27")
        self.assertFalse(matches_session(rec, (2026, 2027)))
        self.assertTrue(matches_session(rec, (2025, 2026)))
        self.assertFalse(matches_identity_year(rec, 2026))

    def test_explicit_academic_year_metadata_if_title_has_no_session(self):
        rec = notice("metadata", "MAKAUT student notice", academic_year="2026–2027")
        self.assertTrue(matches_session(rec, (2026, 2027)))

    def test_single_summary_session_fallback(self):
        rec = notice("fallback", "University academic notice",
                     summary="Applicable for session 2026-27")
        self.assertTrue(matches_session(rec, (2026, 2027)))

    def test_ambiguous_summary_sessions_fail_closed(self):
        rec = notice("ambiguous", "University academic notice",
                     summary="Historical 2025-26 and 2026-27 figures")
        self.assertFalse(matches_session(rec, (2026, 2027)))

    def test_unrelated_year_in_raw_text_does_not_override_title(self):
        rec = notice("history",
                     "Registration of Students for Academic Session 2025-26",
                     raw_text="Related to circular from 2026-27")
        self.assertFalse(matches_session(rec, (2026, 2027)))

    def test_detection_timestamp_not_used_for_identity_year(self):
        rec = notice("undated", "General university notice", issue_date=None)
        rec["detected_at"] = "2026-10-26T09:00:00Z"
        self.assertFalse(matches_identity_year(rec, 2026))


class FakeCursor(list):
    def limit(self, limit):
        return FakeCursor(self[:limit])


class FakeNoticeCollection:
    def __init__(self, rows):
        self.rows = rows

    def find(self, query):
        # The actual year/session/topic validation must run in retrieve.py.
        if query.get("status") != "processed":
            return FakeCursor([])
        return FakeCursor(self.rows)


class FakeIndex:
    def __init__(self, rows):
        self.rows = rows

    def search_records(self, namespace, query):
        return {"result": {"hits": [{"_id": row["notice_id"]} for row in self.rows]}}


def import_retrieve_offline(rows):
    """Import real retrieval functions with fakes for external services."""
    collection = FakeNoticeCollection(rows)
    fake_dotenv = types.ModuleType("dotenv")
    fake_dotenv.load_dotenv = lambda: None
    fake_pinecone = types.ModuleType("pinecone")
    class FakePineconeClient:
        def __init__(self, api_key):
            pass

        def Index(self, name):
            return FakeIndex(rows)
    fake_pinecone.Pinecone = FakePineconeClient
    fake_pymongo = types.ModuleType("pymongo")
    class FakeClient:
        def __init__(self, uri):
            pass

        def __getitem__(self, key):
            return self

        def find(self, query):
            return collection.find(query)
    fake_pymongo.MongoClient = FakeClient
    stub_modules = {"dotenv": fake_dotenv, "pinecone": fake_pinecone,
                    "pymongo": fake_pymongo}
    # Do not use patch.dict(sys.modules) here: it restores the whole modules
    # dictionary snapshot, evicting e.g. newly imported _zoneinfo C extensions.
    # Some Python versions then crash in interpreter shutdown (none_dealloc).
    # Restore only our three exact stub entries.
    missing = object()
    previous = {name: sys.modules.get(name, missing) for name in stub_modules}
    try:
        sys.modules.update(stub_modules)
        path = Path(__file__).resolve().parents[1] / "retrieve.py"
        spec = importlib.util.spec_from_file_location("_test_academic_retrieve", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        for name, value in previous.items():
            if value is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value
    return module


class RetrievalIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.old = notice("old", "Registration of Students for Academic Session 2025-2026")
        self.new = notice("new", "Registration of Students for Academic Session 2026-27")
        self.wbjee_old = notice("wbjee_old",
                                "Document verification and admission for WBJEEB-2025 allotted students")
        self.wbjee_new = notice("wbjee_new",
                                "Document verification and admission for WBJEEB-2026 allotted students")
        self.module = import_retrieve_offline([
            self.old, self.new, self.wbjee_old, self.wbjee_new
        ])

    def _ids(self, question, **kwargs):
        return [r["notice_id"] for r in self.module.retrieve_filtered_notices(
            question, top_k=10, **kwargs
        )]

    def test_registration_explicit_session_selects_only_requested_one(self):
        self.assertEqual(
            self._ids("Show registration of students for academic session 2026-27"),
            ["new"])

    def test_registration_unqualified_pair_is_still_session(self):
        self.assertEqual(
            self._ids("Show registration of students notices 2026-27"),
            ["new"])

    def test_registration_session_query_never_uses_2026_issue_date(self):
        self.assertNotIn(
            "old", self._ids("Registration of students for academic year 2026-2027"))

    def test_registration_2025_26_explicit_session(self):
        self.assertEqual(
            self._ids("Show registration of students for academic session 2025-26"),
            ["old"])

    def test_2026_year_only_does_not_match_2025_26_end_year(self):
        self.assertEqual(self._ids("Show registration of students for 2026"), ["new"])

    def test_2027_year_only_does_not_match_end_of_2026_27(self):
        self.assertEqual(self._ids("Show registration of students for 2027"), [])

    def test_wbjee_exam_year_2026_strict(self):
        self.assertEqual(
            self._ids("Find document verification and admission WBJEE 2026"),
            ["wbjee_new"])

    def test_wbjee_exam_year_2025_strict(self):
        self.assertEqual(
            self._ids("Find document verification and admission WBJEE 2025"),
            ["wbjee_old"])

    def test_missing_session_returns_no_records(self):
        self.assertEqual(
            self._ids("Registration of students for academic session 2028-29"), [])

    def test_session_comparison_forced_2025(self):
        self.assertEqual(
            self._ids("Compare registration of students 2025-26 with 2026-27",
                      force_year=2025),
            ["old"])

    def test_session_comparison_forced_2026(self):
        self.assertEqual(
            self._ids("Compare registration of students 2025-26 with 2026-27",
                      force_year=2026),
            ["new"])

    def test_session_comparison_does_not_treat_2027_as_third_year(self):
        self.assertEqual(
            self._ids("Compare registration of students 2025-26 with 2026-27",
                      force_year=2027),
            [])

    def test_unqualified_multi_session_question_requires_separate_scopes(self):
        self.assertEqual(
            self._ids("Compare registration of students 2025-26 and 2026-27"),
            [])

    def test_latest_notices_for_session_do_not_use_global_chronology(self):
        self.assertFalse(self.module.is_pure_time_query(
            "latest notices for academic session 2026-27"))
        ids = [r["notice_id"] for r in self.module.retrieve_context(
            "latest notices for academic session 2026-27", top_k=5)]
        self.assertEqual(ids, ["new"])

    def test_direct_time_retrieval_preserves_session_scope(self):
        ids = [r["notice_id"] for r in self.module.retrieve_time_based(
            "latest notices for 2026-27", top_k=5)]
        self.assertEqual(ids, ["new"])

    def test_latest_calendar_year_does_not_mean_issue_year(self):
        ids = [r["notice_id"] for r in self.module.retrieve_context(
            "latest registration of students notices 2026", top_k=5)]
        self.assertEqual(ids, ["new"])

    def test_semantic_retrieval_rejects_old_session_overlapping_year(self):
        ids = [r["notice_id"] for r in self.module.retrieve_semantic(
            "University notice for academic session 2026-27", top_k=5)]
        self.assertEqual(ids, ["new"])

    def test_semantic_retrieval_does_not_fallback_wrong_session(self):
        answer = self.module.retrieve_semantic("2028-29 university circular", top_k=5)
        self.assertEqual(answer, [])

    def test_semantic_retrieval_does_not_fallback_wrong_year(self):
        answer = self.module.retrieve_semantic("university circular 2030", top_k=5)
        self.assertEqual(answer, [])


if __name__ == "__main__":
    unittest.main()
