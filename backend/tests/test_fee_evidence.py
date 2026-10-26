"""Regression tests: an admission fee must never become an application fee.

Run from backend/: python -m unittest discover -s tests -p 'test_fee_evidence.py'
No external APIs are called.
"""
import unittest

from Module4.fee_utils import (
    answer_fee_question, labeled_fee_evidence, query_fee_kind,
)
from Module4.evidence import missing_amount_guidance


def _record(raw_text="", *, amount=None, fee_type=None, key_points=None):
    return {
        "title": "WBJEE Notice",
        "url": "https://makautwb.ac.in/wbjee.pdf",
        "notice_id": "wbjee-test",
        "raw_text": raw_text,
        "structured_data": {
            "fees": {"amount": amount, "currency": "INR", "type": fee_type},
            "key_points": key_points or [],
        },
    }


class FeeEvidenceTests(unittest.TestCase):
    def test_no_application_fee_from_admission_only(self):
        r = _record("Application fee is not listed. Admission fee: Rs. 500.",
                    amount="500", fee_type="admission")
        self.assertEqual(labeled_fee_evidence(r, "application"), [])
        self.assertEqual(len(labeled_fee_evidence(r, "admission")), 1)

    def test_two_fees_in_same_sentence_are_scoped_independently(self):
        r = _record("Application fee: Rs. 200, admission fee: Rs. 500.")
        app = labeled_fee_evidence(r, "application")
        adm = labeled_fee_evidence(r, "admission")
        self.assertEqual(app[0][1], "Rs. 200")
        self.assertEqual(adm[0][1], "Rs. 500")
        self.assertNotIn("Rs. 500", app[0][0])

    def test_two_fees_on_separate_lines(self):
        r = _record("Admission fee: INR 800\nApplication fee: ₹ 300")
        self.assertEqual(labeled_fee_evidence(r, "application")[0][1], "₹ 300")

    def test_amount_before_label(self):
        r = _record("Rs. 250 application fee; Rs. 900 admission fee")
        self.assertEqual(labeled_fee_evidence(r, "application")[0][1], "Rs. 250")
        self.assertEqual(labeled_fee_evidence(r, "admission")[0][1], "Rs. 900")

    def test_unrelated_prior_amount_not_used(self):
        r = _record("Admission fee Rs. 500, application fee is not specified.")
        self.assertEqual(labeled_fee_evidence(r, "application"), [])

    def test_cross_sentence_regression(self):
        r = _record("The application fee was not mentioned.\nThe admission fee is Rs. 500.")
        self.assertEqual(labeled_fee_evidence(r, "application"), [])

    def test_generic_legacy_amount_not_trusted_for_specific_type(self):
        r = _record(amount="500")
        self.assertEqual(labeled_fee_evidence(r, "application"), [])
        self.assertEqual(labeled_fee_evidence(r, "admission"), [])

    def test_missing_amount_guidance_rejects_generic_admission_amount(self):
        r = _record("Admission fee: Rs. 500.",
                    amount="500", fee_type="admission")
        answer = missing_amount_guidance("What is the application fee?", r)
        self.assertIn("couldn't find an application-fee amount", answer)
        self.assertNotIn("500", answer)

    def test_missing_amount_guidance_defers_when_application_fee_exists(self):
        r = _record("Application fee: Rs. 200. Admission fee: Rs. 500.")
        self.assertIsNone(
            missing_amount_guidance("What is the application fee?", r)
        )

    def test_structured_explicit_label_fallback(self):
        r = _record(key_points=["Application fee is INR 150, payable online."])
        self.assertEqual(labeled_fee_evidence(r, "application")[0][1], "INR 150")

    def test_fee_label_ending_at_newline(self):
        r = _record("Application fee:\nRs. 600\nAdmission fee: Rs. 1000")
        self.assertEqual(labeled_fee_evidence(r, "application")[0][1], "Rs. 600")

    def test_no_numeric_fees_in_free_or_nil_statement(self):
        r = _record("Application fee: NIL. Admission fee: Rs. 500.")
        self.assertEqual(labeled_fee_evidence(r, "application"), [])

    def test_provisional_merged_fee_is_not_confirmed(self):
        r = _record(key_points=[
            "Extracted application fee candidate requiring verification: 500 INR"
        ])
        self.assertEqual(labeled_fee_evidence(r, "application"), [])

    def test_unrelated_review_in_raw_does_not_hide_fee(self):
        r = _record(
            "Documents requiring verification. Application fee: Rs. 275."
        )
        self.assertEqual(labeled_fee_evidence(r, "application")[0][1], "Rs. 275")

    def test_question_fee_type_classification(self):
        cases = [
            ("What is the application fee?", "application"),
            ("Show the admission fee", "admission"),
            ("Fees for admission?", "admission"),
            ("What is the registration fee?", "registration"),
            ("How much is the exam fee?", "examination"),
            ("What is the fee in this notice?", None),
            ("What is the application fee for admission?", "application"),
            ("Compare application fee and admission fee", None),
            ("What is the counselling fee?", "counselling"),
        ]
        for q, want in cases:
            with self.subTest(question=q):
                self.assertEqual(query_fee_kind(q), want)


class FeeAnswerTests(unittest.TestCase):
    @staticmethod
    def answer(question, record, field="fees"):
        return answer_fee_question(
            question, record,
            source=record["url"],
            title=record["title"],
        )

    def test_application_fee_never_uses_admission_fee(self):
        r = _record("Application fee not specified. Admission fee: Rs. 500.",
                    amount="500", fee_type="admission")
        answer = self.answer("What is the application fee?", r, "fees")
        self.assertIn("cannot verify an application-fee amount", answer)
        self.assertNotIn("Rs. 500", answer)
        self.assertIn("https://makautwb.ac.in/wbjee.pdf", answer)

    def test_application_fee_answer_contains_correct_amount(self):
        r = _record("Application fee: ₹ 150. Admission fee: ₹ 950")
        answer = self.answer("What is the application fee?", r, "fees")
        self.assertIn("₹ 150", answer)
        self.assertNotIn("₹ 950", answer)

    def test_admission_fee_answer_contains_correct_amount(self):
        r = _record("Application fee: Rs. 150. Admission fee: Rs. 950")
        answer = self.answer("What is the admission fee?", r, "fees")
        self.assertIn("Rs. 950", answer)
        self.assertNotIn("Rs. 150", answer)

    def test_comparison_preserves_both_fee_categories(self):
        r = _record("Application fee: ₹ 200. Admission fee: ₹ 900")
        answer = self.answer("Compare application fee and admission fee", r)
        self.assertIn("₹ 200", answer)
        self.assertIn("₹ 900", answer)

    def test_unlabeled_fee_does_not_become_application_fee(self):
        r = _record(amount="1000", fee_type=None)
        answer = self.answer("Application fee?", r, "fees")
        self.assertIn("cannot verify an application-fee amount", answer)
        self.assertNotIn("1000", answer)


if __name__ == "__main__":
    unittest.main()
