"""Regression tests for document verification / required-document answers.

Run from the repo root:
PYTHONPATH=backend python -m unittest discover -s backend/tests -p test_document_evidence.py

Tests are isolated: no MongoDB, Pinecone, Groq or PDF network access.
"""
import unittest

from Module4.document_utils import answer_document_question


SOURCE = "Official source: https://makautwb.ac.in/datas/users/0-wbjee.pdf"
TITLE = "WBJEE 2026 Document Verification Notice"


def notice(raw=None, *, docs=None, points=None, action=None):
    return {
        "notice_id": "test-wbjee",
        "title": TITLE,
        "url": "https://makautwb.ac.in/datas/users/0-wbjee.pdf",
        "raw_text": raw,
        "structured_data": {
            "required_documents": docs or [],
            "key_points": points or [],
            "action_required": action,
        },
    }


def answer(record):
    return answer_document_question(record, TITLE, SOURCE)


class RequiredDocumentsTests(unittest.TestCase):
    def test_verification_without_document_names_is_not_a_list(self):
        result = answer(notice(
            "Document verification will be conducted at the university on 10 October."
        ))
        self.assertIn("couldn't verify a list of required documents", result)
        self.assertNotIn("- Document verification", result)
        self.assertIn("makautwb.ac.in", result)

    def test_generic_keypoint_does_not_short_circuit_real_pdf_list(self):
        raw = (
            "Document verification instructions.\n"
            "Required documents:\n"
            "1. Class 10 mark sheet\n"
            "2. Class 12 mark sheet\n"
            "3. WBJEE Rank Card\n"
            "4. Aadhaar Card\n"
            "5. Allotment Card"
        )
        result = answer(notice(raw, points=["Report for document verification"]))
        for term in ("Class 10 mark sheet", "Class 12 mark sheet",
                     "WBJEE Rank Card", "Aadhaar Card", "Allotment Card"):
            self.assertIn(term, result)

    def test_combined_list_preserves_all_named_documents(self):
        raw = (
            "Bring original Class 10 and Class 12 mark sheets, Admit Card, "
            "AADHAAR, WBJEE Rank Card, Allotment Card, caste/EWS certificates, "
            "and domicile certificate (if applicable) for document verification."
        )
        result = answer(notice(raw))
        for term in ("Class 10", "Class 12", "Admit Card", "AADHAAR",
                     "WBJEE Rank Card", "Allotment Card",
                     "caste/EWS certificates", "domicile certificate",
                     "if applicable"):
            self.assertIn(term, result)

    def test_original_and_copy_requirements_retained(self):
        raw = (
            "Documents required for verification:\n"
            "1. Class X mark sheet\n"
            "2. Rank Card\n"
            "Bring originals and two self-attested photocopies of each document."
        )
        result = answer(notice(raw))
        self.assertIn("Class X mark sheet", result)
        self.assertIn("Rank Card", result)
        self.assertIn("two self-attested photocopies", result)

    def test_irrelevant_mentioned_documents_not_assumed_required(self):
        raw = (
            "Application form submission happens online.\n"
            "Later, document verification will be conducted on campus.\n"
            "Students should report at 10 AM."
        )
        result = answer(notice(raw))
        self.assertIn("couldn't verify a list of required documents", result)
        self.assertNotIn("- Application form", result)

    def test_verification_announcement_does_not_make_application_form_required(self):
        raw = (
            "Document verification will be conducted on 10 October.\n"
            "The application form is available on the admission portal.\n"
            "For dates, visit the university website."
        )
        result = answer(notice(raw))
        self.assertIn("couldn't verify a list", result)
        self.assertNotIn("- The application form", result)

    def test_no_aadhaar_required_phrasing(self):
        raw = (
            "No Aadhaar Card is required.\n"
            "Bring original Rank Card for physical verification."
        )
        result = answer(notice(raw))
        self.assertNotIn("- No Aadhaar", result)
        self.assertIn("Rank Card", result)

    def test_explicitly_not_required_document_is_excluded(self):
        raw = (
            "Not required to bring Aadhaar Card.\n"
            "Bring the WBJEE Rank Card for verification."
        )
        result = answer(notice(raw))
        self.assertNotIn("- Not required to bring Aadhaar Card", result)
        self.assertIn("WBJEE Rank Card", result)

    def test_pdf_text_has_priority_over_mismatched_structured_data(self):
        raw = "For verification, bring the WBJEE Rank Card."
        result = answer(notice(raw, docs=["Domicile certificate", "Income certificate"]))
        self.assertIn("WBJEE Rank Card", result)
        self.assertNotIn("Domicile certificate", result)
        self.assertNotIn("Income certificate", result)

    def test_no_document_guessing_when_pdf_is_blank_and_schema_empty(self):
        result = answer(notice(None, points=["Document verification required"]))
        self.assertIn("couldn't verify a list", result)
        for term in ("Aadhaar", "mark sheet", "rank card", "domicile"):
            self.assertNotIn(term, result.casefold())

    def test_legacy_record_without_ocr_uses_explicit_extracted_documents(self):
        result = answer(notice(None, docs=[
            "Admit Card (original)", "EWS certificate (if applicable)"
        ]))
        self.assertIn("Admit Card (original)", result)
        self.assertIn("EWS certificate (if applicable)", result)
        self.assertIn("not cross-checked", result)

    def test_legacy_record_without_ocr_uses_specific_keypoints(self):
        result = answer(notice(None, points=[
            "Candidates must bring their Class 12 marksheet.",
            "Document verification is scheduled for Tuesday.",
        ]))
        self.assertIn("Class 12 marksheet", result)
        self.assertNotIn("- Document verification", result)

    def test_action_required_only_generic_is_not_a_document_list(self):
        result = answer(notice(None, action="Submit documents for verification"))
        self.assertIn("couldn't verify a list", result)

    def test_document_list_in_raw_is_read_beyond_first_two_snippets(self):
        raw = (
            "Notice to students.\n"
            + "\n".join(f"Introduction paragraph {i}." for i in range(30))
            + "\nThe following documents are required:\n"
            "1. Original Admit Card\n"
            "2. Mark sheet\n"
            "3. Caste certificate (where relevant)"
        )
        result = answer(notice(raw))
        self.assertIn("Original Admit Card", result)
        self.assertIn("Mark sheet", result)
        self.assertIn("Caste certificate", result)

    def test_unsupported_or_optional_document_is_not_made_mandatory(self):
        raw = "Required documents: domicile certificate (if applicable)."
        result = answer(notice(raw))
        self.assertIn("domicile certificate (if applicable)", result)

    def test_document_requirements_in_prose(self):
        result = answer(notice(
            "Students must upload their Aadhaar card and Class 10 marksheet."
        ))
        self.assertIn("Aadhaar card", result)
        self.assertIn("Class 10 marksheet", result)

    def test_no_cross_notice_leakage(self):
        first = answer(notice("Required documents: Admit Card."))
        second = answer(notice("Verification instructions are available online."))
        self.assertIn("Admit Card", first)
        self.assertNotIn("Admit Card", second)
        self.assertIn("couldn't verify a list", second)

    def test_copy_requirement_alone_does_not_invent_document_names(self):
        result = answer(notice(
            "Students must bring original documents with attested photocopies."
        ))
        self.assertIn("couldn't verify a list", result)
        self.assertNotIn("- Students must bring", result)


if __name__ == "__main__":
    unittest.main()
