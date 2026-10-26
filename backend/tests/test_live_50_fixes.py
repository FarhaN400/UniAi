"""Regression fixtures for observed failures in the 50 live UniAI questions.
Synthetic records test behavior; actual PDF verification remains separate.
"""
import ast
from pathlib import Path
import re
import types
import unittest
from Module4.document_utils import answer_document_question, _join_wrapped_lines
from notice_quality import summary_warning, display_summary
from test_academic_scope import import_retrieve_offline, notice

def main_functions(*names):
    p = Path(__file__).resolve().parents[1] / "Module4" / "main.py"
    tree = ast.parse(p.read_text())
    subset = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    ns = {"re": re, "display_summary": display_summary,
          "_record_heading": lambda r: (r.get("structured_data") or {}).get("title") or r.get("title"),
          "_record_source": lambda r: "Official source: " + r["url"],
          "_field_answer": lambda *args: "Supported field answer",
          "_verified_application_deadline": lambda *args: None,
          "_plain": str}
    exec(compile(ast.Module(body=subset, type_ignores=[]), str(p), "exec"), ns)
    return ns

class LiveRetrievalRegressions(unittest.TestCase):
    def test_q06_examination_routine_rejects_admission_vacancy(self):
        notices = [notice("bad", "Vacant Seats UG Admission", summary="Qualifying examination"),
                   notice("good", "Examination Routine Odd Semester 2026")]
        r = import_retrieve_offline(notices)
        result = r.retrieve_filtered_notices("Find the latest examination routine notice")
        self.assertEqual([x["notice_id"] for x in result], ["good"])

    def test_q07_wbjee_reporting_excludes_registration_portal(self):
        notices = [notice("bad", "Closure of Registration Portal for WBJEE 2026"),
                   notice("good", "Physical Document Verification and Admission Reporting for WBJEEB-2026")]
        r = import_retrieve_offline(notices)
        result = r.retrieve_filtered_notices("Show admission reporting instructions for WBJEE 2026")
        self.assertEqual([x["notice_id"] for x in result], ["good"])

    def test_q42_holiday_is_not_hostel_closure(self):
        notices = [notice("hostel", "Hostel Closure during Durga Puja Festival"),
                   notice("holiday", "University Holiday Notice for Durga Puja")]
        r = import_retrieve_offline(notices)
        found = r.retrieve_filtered_notices("university holiday during Durga Puja")
        self.assertEqual([x["notice_id"] for x in found], ["holiday"])

    def test_q43_placement_salary_is_a_field_not_topic(self):
        r = import_retrieve_offline([
            notice("wbjee", "WBJEEB-2026 Admission Document Verification")
        ])
        found = r.retrieve_filtered_notices(
            "What is the guaranteed placement salary in the WBJEEB 2026 notice?"
        )
        self.assertEqual([x["notice_id"] for x in found], ["wbjee"])

class LiveDocumentRegressions(unittest.TestCase):
    raw = ("Following documents required for document verification:\n"
           "ii) Students have to carry original Mark sheet/Result of class 10\n"
           "and 12, Admit Card, AADHAAR Card, WBJEE Rank Card,\n"
           "Allotment Card, and valid EWS certificate if applicable along with self-attested\n"
           "photocopies of all documents.\n"
           "iii) West Bengal residents must submit a Domicile Certificate (where applicable).\n")
    def rec(self):
        return {"notice_id":"check","url":"https://makautwb.ac.in/check.pdf",
                "raw_text":self.raw, "structured_data":{"title":"WBJEE 2026 Document Verification"}}

    def test_q01_wrapped_documents_preserved(self):
        text = " ".join(_join_wrapped_lines(self.raw))
        self.assertIn("class 10 and 12, Admit Card", text)
        self.assertIn("WBJEE Rank Card, Allotment Card", text)

    def test_q27_full_checklist(self):
        answer = answer_document_question(self.rec(),"WBJEE 2026",
                    "Official source: https://makautwb.ac.in/check.pdf",
                    question="What documents are required?")
        for term in ["class 10", "and 12", "Rank Card", "Allotment Card",
                     "self-attested", "photocopies", "Domicile Certificate"]:
            self.assertIn(term,answer)

    def test_q30_preserves_domicile_qualifier(self):
        answer = answer_document_question(self.rec(),"WBJEE 2026","source",
                    question="Is a domicile certificate required?")
        self.assertIn("where applicable", answer)
        self.assertNotIn("original Mark sheet", answer)

    def test_q31_preserves_self_attested_photocopies(self):
        answer = answer_document_question(self.rec(),"WBJEE 2026","source",
                    question="Are self-attested photocopies required?")
        self.assertIn("self-attested",answer)
        self.assertIn("photocopies",answer)

class LiveGroundingRegressions(unittest.TestCase):
    def test_q02_inconsistent_jelet_dates_are_flagged(self):
        record=notice("jelet","Reporting dates for JELET-2025 allotted students",
            summary="Reporting dates for JELET 2025: 13-15 Oct 2024 and 18-20 Oct 2024")
        self.assertIsNotNone(summary_warning(record))
        self.assertIsNone(display_summary(record)[0])
        ns=main_functions("format_notice_line")
        answer=ns["format_notice_line"](record)
        self.assertIn("Extraction warning",answer)
        self.assertNotIn("13-15 Oct 2024",answer)

    def test_q02_live_jelet_summary_with_reporting_in_two_rounds(self):
        record = notice(
            "jelet", "Reporting dates for JELET-2025 allotted students",
            summary=(
                "The university instructs JELET-2025 allotted candidates to "
                "report for admission at Haringhata Campus in two rounds: "
                "13‑15 Oct 2024 and 18‑20 Oct 2024."
            ),
        )
        self.assertIsNotNone(summary_warning(record))
        rendered = main_functions("format_notice_line")["format_notice_line"](record)
        self.assertNotIn("Oct 2024", rendered)
        self.assertIn("Extraction warning", rendered)

    def test_q16_deadline_never_promotes_reporting_last_date(self):
        ns=main_functions("_field_answer")
        record=notice("wbjee","WBJEE 2026 Reporting")
        record["structured_data"]["important_dates"]={"last_date":"13-09-2026"}
        answer=ns["_field_answer"]("What is the application deadline?",record,"deadline")
        self.assertIn("not necessarily an application deadline",answer)
        self.assertNotIn("lists a last date of 13-09-2026",answer)

    def test_q18_academic_session_direct_without_llm(self):
        ns=main_functions("_preferred_evidence_record","_direct_fact_answer")
        record=notice("reg","Registration of Students Academic Session 2026-27")
        parsed=types.SimpleNamespace(requested_field=None)
        answer,target=ns["_direct_fact_answer"](
            "Which academic session does the 2026-27 student registration notice concern?",
            [record],parsed)
        self.assertIn("2026-27",answer)
        self.assertIn("https://makautwb.ac.in/reg.pdf",answer)

    def test_q19_reopening_uses_hostel_closure_notice(self):
        ns=main_functions("_preferred_evidence_record")
        docs=[notice("other","Hostel Allotment 2026"),
              notice("target","Hostel Closure during Puja")]
        self.assertEqual(ns["_preferred_evidence_record"](
            "When will the hostel reopen?",docs)["notice_id"],"target")

    def test_q24_eligibility_uses_direct_answer(self):
        ns=main_functions("_preferred_evidence_record","_direct_fact_answer")
        docs=[notice("one","JELET-2025 admission"),
              notice("two","JELET-2025 guidelines")]
        parsed=types.SimpleNamespace(requested_field="eligibility")
        answer,target=ns["_direct_fact_answer"](
            "Give eligibility criteria for JELET 2025",docs,parsed)
        self.assertEqual(answer,"Supported field answer")

    def test_q43_no_guaranteed_salary_without_verified_amount(self):
        ns = main_functions("_field_answer")
        ns["missing_amount_guidance"] = (
            lambda q, r: "No verified guaranteed placement amount."
        )
        record = notice("wbjee", "WBJEEB-2026 Admission Reporting")
        answer = ns["_field_answer"](
            "What is the guaranteed placement salary in the WBJEEB 2026 notice?",
            record,
        )
        self.assertIn("No verified guaranteed placement amount.", answer)
        self.assertIn(record["url"], answer)

    def test_q17_ambiguous_jelet_dates_are_disambiguated(self):
        ns=main_functions("_preferred_evidence_record","_direct_fact_answer")
        docs=[notice("one","JELET-2025 Phase One"),
              notice("two","JELET-2025 Phase Two")]
        parsed=types.SimpleNamespace(requested_field="issue_date")
        answer,target=ns["_direct_fact_answer"](
            "What is the official issue date of the JELET 2025 notice?",docs,parsed)
        self.assertIn("multiple JELET notices",answer)
        self.assertIn("https://makautwb.ac.in/one.pdf", answer)
        self.assertIn("https://makautwb.ac.in/two.pdf", answer)
        self.assertEqual(len(target), 2)

if __name__ == "__main__":
    unittest.main()
