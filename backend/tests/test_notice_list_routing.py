"""Regression tests for distinguishing notice listings from field questions.

Run from backend/: python -m unittest discover -s tests -p 'test_notice_list_routing.py'
"""
import unittest
from types import SimpleNamespace

from Module4.main import _is_list_request


class NoticeListRoutingTests(unittest.TestCase):
    def test_field_questions_do_not_trigger_list(self):
        questions = [
            ("Give me the eligibility criteria for WBJEE 2026", "eligibility"),
            ("Show me the documents required for WBJEE 2026", "documents"),
            ("Provide the application fee from this notice", "fees"),
            ("Give me the official source link for this notice", "source"),
            ("What is the deadline in the WBJEE 2026 notice?", "deadline"),
            ("Give me the eligibility criteria from this notice", "eligibility"),
        ]
        for question, field in questions:
            with self.subTest(question=question):
                self.assertFalse(
                    _is_list_request(question, SimpleNamespace(requested_field=field))
                )

    def test_explicit_notice_list_requests_still_work(self):
        questions = [
            ("List all registration notices", None),
            ("Show recent hostel notices", None),
            ("List notices about scholarship fees", "fees"),
            ("Which notices mention fees?", "fees"),
            ("Show the WBJEE 2026 notice", None),
            ("Are there any hostel notices?", None),
        ]
        for question, field in questions:
            with self.subTest(question=question):
                self.assertTrue(
                    _is_list_request(question, SimpleNamespace(requested_field=field))
                )


if __name__ == "__main__":
    unittest.main()
