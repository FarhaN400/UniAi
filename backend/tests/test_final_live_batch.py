"""Synthetic regressions derived from results_50_after_fixes.csv.

These tests validate behavior; they do not validate any official PDF's factual
contents. Use a fresh live evaluation and human source review before release.
"""
import ast
from pathlib import Path
import re
import sys
import types
import unittest
from unittest.mock import patch

from test_academic_scope import import_retrieve_offline, notice

BACKEND = Path(__file__).resolve().parents[1]


def offline_funcs(path, names, bindings=None):
    source = BACKEND / path
    tree = ast.parse(source.read_text(encoding="utf-8"))
    nodes = [node for node in tree.body
             if isinstance(node, ast.FunctionDef) and node.name in names]
    found = {node.name for node in nodes}
    if found != set(names):
        raise ValueError(f"Missing requested functions: {set(names) - found}")
    ns = {"re": re}
    ns.update(bindings or {})
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), ns)
    return ns


def record_title(record):
    return (record.get("structured_data") or {}).get("title") or record.get("title")


def record_source(record):
    return "Official source: " + record["url"]


def saved_reply(st, question, answer, records=None, **kw):
    return {"answer": answer, "records": list(records or [])}


class FinalRetrievalRegressions(unittest.TestCase):
    def test_student_exam_pattern_finds_internal_assessment_not_routine(self):
        rows = [
            notice("routine", "University Examination Routine for Odd Semester 2026"),
            notice("scheme", "Scheme of Internal Assessment for Theory and Practical "
                   "Subjects and Submission of Internal Assessment Marks"),
            notice("hostel", "Hostel Closure Notice",
                   summary="Students should follow the revised exam pattern"),
            notice("fees", "Examination Fee Payment Notice"),
        ]
        ret = import_retrieve_offline(rows)
        questions = (
            "Give me a process of the new exam pattern.",
            "What is the new exam pattern?",
            "How are internal marks calculated?",
            "Tell me the assessment scheme for theory and practical subjects.",
            "How are project and laboratory marks distributed?",
        )
        for question in questions:
            with self.subTest(question=question):
                self.assertTrue(ret.is_assessment_question(question))
                self.assertEqual(ret.detect_search_topics(question), {"exam"})
                results = ret.retrieve_flexible_context(question, top_k=5)
                self.assertEqual([r["notice_id"] for r in results], ["scheme"])
                self.assertEqual([r["notice_id"] for r in
                                  ret.enforce_source_scope(question, rows)], ["scheme"])

    def test_assessment_query_expands_ocr_snippets_without_inventing_marks(self):
        ret = import_retrieve_offline([])
        raw = (
            "INTERNAL ASSESSMENT. Theory assessment is listed separately.\n"
            "The practical and laboratory components are defined in the table.\n"
            "Submission of internal assessment marks shall follow the schedule.\n"
        )
        matches = ret.extract_relevant_snippets(
            raw, "Give me a process of the new exam pattern.",
            max_snippets=3,
        )
        self.assertTrue(matches)
        self.assertTrue(any("INTERNAL ASSESSMENT" in x for x in matches))
        self.assertFalse(any("30 marks" in x for x in matches))

    def test_assessment_semantic_fallback_still_requires_official_subject(self):
        rows = [
            notice("scheme", "Internal Assessment Scheme for Practical Subjects"),
            notice("routine", "Semester Examination Routine"),
        ]
        ret = import_retrieve_offline(rows)
        original = ret.retrieve_filtered_notices
        semantic_calls = []
        def semantic_stub(question, top_k=5):
            semantic_calls.append(question)
            return [rows[1], rows[0]]
        with patch.object(ret, "retrieve_filtered_notices", return_value=[]):
            with patch.object(ret, "retrieve_semantic", side_effect=semantic_stub):
                matched = ret.retrieve_flexible_context(
                    "What is the new exam pattern?", top_k=3)
        self.assertEqual([r["notice_id"] for r in matched], ["scheme"])
        self.assertIn("internal assessment scheme", semantic_calls[0])
        self.assertEqual([r["notice_id"] for r in original(
            "What is the new exam pattern?", top_k=3)], ["scheme"])

    def test_specific_session_query_does_not_fallback_semantically(self):
        rows = [notice("new", "Internal Assessment Scheme 2026-27")]
        ret = import_retrieve_offline(rows)
        with patch.object(ret, "retrieve_filtered_notices", return_value=[]):
            with patch.object(ret, "retrieve_semantic") as semantic:
                self.assertEqual(ret.retrieve_flexible_context(
                    "What is the internal assessment scheme for 2025-26?"), [])
                semantic.assert_not_called()

    def test_entrance_exam_and_exam_routine_remain_strict(self):
        rows = [
            notice("scheme", "Scheme of Internal Assessment for Theory and Practical"),
            notice("routine", "Examination Routine for Odd Semester 2026"),
            notice("jeca", "JECA-2026 Admission Reporting Notice"),
        ]
        ret = import_retrieve_offline(rows)
        self.assertFalse(ret.is_assessment_question("What is the JECA exam pattern?"))
        self.assertFalse(ret.is_assessment_question("Find the exam timetable"))
        self.assertEqual([r["notice_id"] for r in ret.retrieve_filtered_notices(
            "Find the latest examination routine notice.", sort_latest=True)],
            ["routine"])
        self.assertEqual([r["notice_id"] for r in ret.retrieve_filtered_notices(
            "Find JECA-2026 admission notice")], ["jeca"])

    def test_admission_synonyms_route_to_strict_subject_search(self):
        rows = [
            notice("admissions", "Notice for B.Tech Direct Admission 2026"),
            notice("counselling", "Counselling and Reporting Schedule for Students"),
            notice("seats", "Decentralised Admission for Vacant Seats 2026"),
            notice("hostel", "Hostel Allotment and Room Booking Notice",
                   summary="Admission portal is now available"),
            notice("refund", "Guidelines for Refund of Admission Fees"),
            notice("ragging", "Anti-Ragging Committee and Admission Helpdesk"),
            notice("scholarship", "Scholarship Scheme 2026",
                   summary="Admission is required to apply"),
        ]
        ret = import_retrieve_offline(rows)
        expected = {"admissions", "counselling", "seats"}
        for question in (
            "Give me the recent notice of addmission.",
            "Show me the five most recent admission notices.",
            "List latest admissions circulars.",
        ):
            with self.subTest(question=question):
                found = ret.retrieve_filtered_notices(question, top_k=5,
                                                      sort_latest=True)
                self.assertEqual({r["notice_id"] for r in found}, expected)
                self.assertEqual(ret.enforce_source_scope(question, rows), [
                    rows[0], rows[1], rows[2],
                ])

    def test_generic_latest_is_unfiltered_and_named_topics_survive(self):
        rows = [
            notice("adm", "B.Tech Direct Admission Notice"),
            notice("hostel", "Hostel Closure During Durga Puja"),
            notice("exam", "University Examination Routine"),
        ]
        ret = import_retrieve_offline(rows)
        self.assertTrue(ret.is_pure_time_query("Show five latest MAKAUT notices"))
        self.assertFalse(ret.is_pure_time_query(
            "Give me the recent notice of addmission."))
        self.assertEqual(ret.detect_search_topics(
            "Find WBJEE 2026 admission notices"), {"wbjee"})
        self.assertEqual(ret.detect_search_topics(
            "Show recent hostel notices"), {"hostel"})
        self.assertEqual({r["notice_id"] for r in ret.retrieve_filtered_notices(
            "Show recent hostel notices")}, {"hostel"})

    def test_q03_exclude_anti_ragging_and_refund_from_hostel(self):
        rows = [
            notice("hostel1", "Hostel Allotment Application for AY 2026-2027"),
            notice("hostel2", "Hostel Closure during Durga Puja Festival"),
            notice("rag", "Constitution of Anti-Ragging Committee",
                   summary="Includes a hostel representative"),
            notice("refund", "Guidelines for Refund of Fees",
                   summary="Hostel residents may request a refund"),
        ]
        ret = import_retrieve_offline(rows)
        found = ret.retrieve_filtered_notices(
            "Show recent hostel notices.", top_k=5, sort_latest=True)
        self.assertEqual({r["notice_id"] for r in found}, {"hostel1", "hostel2"})

    def test_q05_scholarship_requires_named_topic(self):
        rows = [
            notice("good", "Invitation for AICTE Doctoral Fellowship Scheme"),
            notice("bad", "University Registration Notice",
                   summary="Includes scholarship applications"),
        ]
        ret = import_retrieve_offline(rows)
        found = ret.retrieve_filtered_notices("List five scholarship notices.", top_k=5)
        self.assertEqual([r["notice_id"] for r in found], ["good"])

    def test_q06_generic_examination_routine_rejects_phd_rpe(self):
        rows = [
            notice("phd", "RPE 2026 Course and Examination Schedule for PhD Candidates"),
            notice("routine", "University Examination Routine for Odd Semester 2026"),
        ]
        ret = import_retrieve_offline(rows)
        found = ret.retrieve_filtered_notices(
            "Find the latest examination routine notice.", sort_latest=True)
        self.assertEqual([r["notice_id"] for r in found], ["routine"])

    def test_q06_no_routine_means_no_relevant_notice(self):
        ret = import_retrieve_offline([
            notice("phd", "RPE 2026 Course and Examination Schedule for PhD Candidates")
        ])
        self.assertEqual(ret.retrieve_filtered_notices(
            "Find the latest examination routine notice."), [])

    def test_q17_jelet_2025_issue_date_cannot_use_generic_lateral_notice(self):
        rows = [
            notice("generic", "Opening Phase 1 Registration B.Tech Lateral AY 2025-26",
                   summary="Students allotted under JELET must register"),
            notice("specific", "Reporting dates for JELET-2025 allotted students",
                   issue_date="11-12-2025"),
        ]
        ret = import_retrieve_offline(rows)
        found = ret.retrieve_filtered_notices(
            "What is the official issue date of the JELET 2025 notice?",
            top_k=5,
        )
        self.assertEqual([r["notice_id"] for r in found], ["specific"])

    def test_q24_jelet_eligibility_cannot_use_btech_lateral_registration(self):
        rows = [
            notice("generic", "Opening of Phase 1 Registration for B.Tech Lateral "
                   "and MCA Lateral for AY 2025-26",
                   summary="JELET students may register."),
            notice("specific", "JELET-2025 admission guidance"),
        ]
        ret = import_retrieve_offline(rows)
        found = ret.retrieve_filtered_notices(
            "Give me eligibility criteria for JELET 2025.", top_k=5
        )
        self.assertEqual([r["notice_id"] for r in found], ["specific"])

    def test_q42_closure_is_not_hostel_allotment(self):
        rows = [
            notice("allotment", "Hostel Allotment Application AY 2026-27"),
            notice("closure", "Hostel Closure during Durga Puja"),
        ]
        ret = import_retrieve_offline(rows)
        found = ret.retrieve_filtered_notices(
            "hostel closure during Durga Puja", top_k=5)
        self.assertEqual([r["notice_id"] for r in found], ["closure"])

    def test_q42_durga_puja_cannot_select_viswakarma(self):
        rows = [
            notice("wrong", "Declaration of University Holiday on Viswakarma Puja"),
            notice("right", "Declaration of University Holiday during Durga Puja"),
        ]
        ret = import_retrieve_offline(rows)
        found = ret.retrieve_filtered_notices(
            "university holiday during Durga Puja", top_k=5)
        self.assertEqual([r["notice_id"] for r in found], ["right"])

    def test_q42_no_durga_holiday_avoids_unrelated_source(self):
        ret = import_retrieve_offline([
            notice("wrong", "University Holiday on Viswakarma Puja")
        ])
        self.assertEqual(ret.retrieve_filtered_notices(
            "university holiday during Durga Puja"), [])

    def test_q23_refund_notice_is_not_generic_admission_notice(self):
        rows = [
            notice("wrong", "Guidelines for Refund of Admission Fees due to Withdrawal"),
            notice("right", "B.Tech Admission Notice for Session 2026-2027"),
        ]
        ret = import_retrieve_offline(rows)
        found = ret.retrieve_filtered_notices(
            "Are both application fees and admission fees mentioned "
            "in the 2026 admission notice?", top_k=5)
        self.assertEqual([r["notice_id"] for r in found], ["right"])


class FinalRoutingRegressions(unittest.TestCase):
    def _main(self, *names, extra=None):
        ns = {
            "_record_heading": record_title,
            "_record_source": record_source,
            "_save_reply": saved_reply,
            "_field_answer": lambda *args: "An explicitly supported fact.",
        }
        ns.update(extra or {})
        return offline_funcs("Module4/main.py", set(names), ns)

    def test_informal_exam_pattern_returns_sourced_assessment_facts(self):
        record = notice("assessment",
                        "Scheme of Internal Assessment for Theory and Practical Subjects")
        record["structured_data"]["summary"] = (
            "Defines the internal assessment scheme for theory and practical subjects."
        )
        record["structured_data"]["key_points"] = [
            "Theory internal assessment carries 30 marks: 15 for CA, "
            "10 for Assignment/Quiz, and 5 for Attendance/Participation.",
            "Practical assessment is awarded by the concerned faculty "
            "based on PCA records.",
        ]
        ns = self._main("_assessment_answer_from_records", extra={
            "_plain": str,
            "display_summary": lambda r: (r["structured_data"]["summary"], None),
        })
        for q in (
            "Give me the process of the new exam pattern.",
            "How are internal marks calculated?",
            "What is the marking scheme for theory and practical subjects?",
        ):
            with self.subTest(q=q):
                message, cited = ns["_assessment_answer_from_records"](q, [record])
                self.assertIn("Scheme of Internal Assessment", message)
                self.assertIn("Official source: https://makautwb.ac.in/assessment.pdf", message)
                self.assertNotIn("could not find this information", message)
                self.assertEqual(cited, [record])
        message, _ = ns["_assessment_answer_from_records"](
            "Give me the process of the new exam pattern.", [record])
        self.assertIn("internal assessment", message.casefold())
        self.assertIn("not be taken", message.casefold())

    def test_project_laboratory_marks_never_invent_specific_allocation(self):
        record = notice("assessment", "Internal Assessment Scheme for Practical Subjects")
        record["structured_data"]["key_points"] = [
            "Practical assessment uses PCA records evaluated by the faculty."
        ]
        ns = self._main("_assessment_answer_from_records", extra={
            "_plain": str,
            "display_summary": lambda r: (None, None),
        })
        response, cited = ns["_assessment_answer_from_records"](
            "How are project and laboratory marks distributed?", [record])
        self.assertIn("Practical assessment uses PCA records", response)
        self.assertIn("project-marks allocation couldn't be verified", response)
        self.assertIn("laboratory-marks allocation couldn't be verified", response)
        self.assertNotIn("30 marks", response)
        self.assertEqual(cited, [record])

    def test_ambiguous_assessment_notices_offer_named_choices(self):
        rows = [
            notice("old", "Assessment Scheme for Theory 2025"),
            notice("new", "Assessment Scheme for Theory 2026"),
        ]
        ns = self._main("_assessment_answer_from_records", extra={
            "_plain": str,
            "display_summary": lambda r: (None, None),
        })
        response, cited = ns["_assessment_answer_from_records"](
            "How are internal marks calculated?", rows)
        self.assertIn("Please choose the relevant notice", response)
        self.assertEqual(cited, rows)
        self.assertIn("https://makautwb.ac.in/old.pdf", response)
        self.assertIn("https://makautwb.ac.in/new.pdf", response)

    def test_generic_admission_is_a_new_topic_after_hostel(self):
        hostel = notice("hostel", "Hostel Closure during Durga Puja Festival",
                        summary="Admission applicants may also use the hostel")
        ns = offline_funcs(
            "Module4/query_understanding.py",
            {"_detect_explicit_topic_or_entity", "explicitly_changes_notice_topic"},
            {
                "TOPIC_MARKERS": {
                    "hostel": r"\bhostels?\b",
                    "admission": r"\b(?:admissions?|addmissions?)\b",
                },
                "academic_sessions": lambda text: [],
                "matches_session": lambda *args: False,
            },
        )
        self.assertEqual(ns["_detect_explicit_topic_or_entity"](
            "What papers should I carry for admission?"), "admission")
        self.assertEqual(ns["_detect_explicit_topic_or_entity"](
            "Any addmission documents?"), "admission")
        self.assertTrue(ns["explicitly_changes_notice_topic"](
            "What papers should I carry for admission?", hostel))
        self.assertFalse(ns["explicitly_changes_notice_topic"](
            "What is its official source?", hostel))

    def test_real_fallback_parser_does_not_reuse_hostel(self):
        from Module4.conversation_state import ConversationState
        hostel = notice("hostel", "Hostel Closure During Durga Puja",
                        summary="Mentions admission in a footnote")
        st = ConversationState()
        st.set_active_notice(hostel)
        markers = {
            "hostel": r"\bhostels?\b",
            "admission": r"\b(?:admissions?|addmissions?)\b",
        }
        switches = offline_funcs(
            "Module4/query_understanding.py",
            {"_detect_explicit_topic_or_entity", "explicitly_changes_notice_topic"},
            {"TOPIC_MARKERS": markers,
             "academic_sessions": lambda text: [],
             "matches_session": lambda *args: False},
        )
        query = offline_funcs(
            "Module4/query_understanding.py",
            {"_detect_explicit_topic_or_entity", "fallback_understand_query"},
            {
                "_is_conversational_casual": lambda q: False,
                "_explicit_temporal_notice_request": lambda q: None,
                "_extract_ordinal_from_text": lambda q: None,
                "_extract_requested_field": lambda q: (
                    "documents" if "papers" in q.lower() else None
                ),
                "_extract_count_from_text": lambda q: None,
                "explicitly_changes_notice_topic": switches[
                    "explicitly_changes_notice_topic"
                ],
                "QueryUnderstandingResult": types.SimpleNamespace,
            },
        )
        result = query["fallback_understand_query"](
            "What papers should I carry for admission?", st)
        self.assertEqual(result.intent, "topic_search")
        self.assertFalse(result.use_active_notice)
        self.assertEqual(result.requested_field, "documents")

    def test_wbjee_allotment_guidance_never_invents_universal_steps(self):
        ns = self._main("_is_unqualified_allotment_guidance",
                        "_allotment_guidance_choices", extra={
                            "format_notice_list": lambda rows: "\n".join(
                                record_title(r) + " " + record_source(r) for r in rows
                            )
                        })
        question = "I got a seat through WBJEE. What should I do next?"
        self.assertTrue(ns["_is_unqualified_allotment_guidance"](question))
        self.assertFalse(ns["_is_unqualified_allotment_guidance"](
            "Give me the WBJEE 2026 reporting instructions"))
        notices = [
            notice("portal", "Closure of Registration Portal for WBJEE 2026"),
            notice("report", "WBJEEB-2026 Admission Reporting and Document Verification"),
        ]
        answer, chosen = ns["_allotment_guidance_choices"](question, notices)
        self.assertIn("Which year and round", answer)
        self.assertIn("WBJEEB-2026 Admission Reporting", answer)
        self.assertEqual(chosen[0]["notice_id"], "report")
        self.assertNotIn("carry Aadhaar", answer)

    def test_ambiguous_admission_documents_request_asks_for_process(self):
        ns = self._main("_is_generic_admission_documents",
                        "_admission_document_choices")
        q = "What papers should I carry for admission?"
        self.assertTrue(ns["_is_generic_admission_documents"](
            q, "documents", {"admission"}))
        self.assertFalse(ns["_is_generic_admission_documents"](
            "What documents do I need for WBJEE 2026?", "documents", {"wbjee"}))
        notices = [
            notice("wbjee", "WBJEEB-2026 Admission Document Verification"),
            notice("hostel", "Hostel Closure"),
        ]
        answer, chosen = ns["_admission_document_choices"](notices[:1])
        self.assertIn("Which admission process and year", answer)
        self.assertIn("https://makautwb.ac.in/wbjee.pdf", answer)
        self.assertEqual([r["notice_id"] for r in chosen], ["wbjee"])

    def test_live_chat_clears_hostel_on_failure_and_stays_on_admission(self):
        from Module4.conversation_state import ConversationState
        hostel = notice("hostel", "Hostel Closure during Durga Puja Festival",
                        summary="Admission rules are mentioned on another page")
        wbjee = notice("wbjee", "WBJEEB-2026 Document Verification and Admission Reporting")
        other = notice("other", "B.Tech Direct Admission Guidelines 2026")
        ret = import_retrieve_offline([hostel, wbjee, other])
        st = ConversationState()
        st.append_turn("When do we leave the hostel during Puja?",
                       "Hostel closure information", records=[hostel],
                       active_notice=hostel)

        change = offline_funcs(
            "Module4/query_understanding.py",
            {"explicitly_changes_notice_topic"},
            {"TOPIC_MARKERS": {
                "hostel": r"\bhostels?\b",
                "admission": r"\b(?:admissions?|addmissions?)\b",
                "wbjee": r"\bwbjeeb?\b",
            },
             "academic_sessions": lambda text: [],
             "matches_session": lambda *args: False},
        )["explicitly_changes_notice_topic"]
        parser_mod = types.ModuleType("Module4.query_understanding")
        parser_mod.fallback_understand_query = lambda q, state=None: types.SimpleNamespace(
            intent="topic_search", count=None, requested_field=(
                "documents" if "papers" in q.lower() else None
            ), use_active_notice=False,
        )
        ns = self._main(
            "ask_uniai", "_save_reply", "_is_unqualified_allotment_guidance",
            "_allotment_guidance_choices", "_is_generic_admission_documents",
            "_admission_document_choices",
            extra={
                "ConversationState": ConversationState,
                "explicitly_changes_notice_topic": change,
                "_out_of_scope": lambda q: False,
                "_is_comparison_query": lambda q: False,
                "extract_requested_count": lambda q: None,
                "_is_single_target": lambda q, p: False,
                "_is_list_request": lambda q, p=None: False,
                "_direct_fact_answer": lambda *args: None,
                "_field_answer": lambda *args: "WRONG HOSTEL FOLLOW-UP",
                "_no_matches": lambda q: "No matching notice",
                "format_notice_list": lambda rows: "\n".join(
                    record_title(r) + " " + record_source(r) for r in rows),
                "_safe_grounded_answer": lambda question, rows, state, **kw:
                    ns["_save_reply"](state, question, "Answer service temporarily "
                                       "unavailable", records=[]),
                "os": __import__("os"),
            },
        )
        with patch.dict(sys.modules, {
            "retrieve": ret,
            "Module4.query_understanding": parser_mod,
        }):
            # Simulate a failed provider answer when the student changes from
            # hostel to WBJEE. The old hostel notice must be cleared.
            first = ns["ask_uniai"](
                "Tell me about WBJEE 2026 admission reporting", state=st)
            self.assertIn("temporarily unavailable", first)
            self.assertIsNone(st.get_active_notice())

            # Next vague admission question must search admissions afresh,
            # never run an answer-document lookup against the hostel notice.
            second = ns["ask_uniai"](
                "What papers should I carry for admission?", state=st)
            self.assertIn("Which admission process and year", second)
            self.assertNotIn("Hostel Closure", second)
            self.assertNotIn("WRONG HOSTEL", second)
            self.assertTrue(st.get_last_answer_records())
            self.assertTrue(all("Hostel" not in record_title(r)
                                for r in st.get_last_answer_records()))

    def test_q11_issued_yesterday_is_temporal_not_generic_search(self):
        f = offline_funcs("Module4/query_understanding.py",
                          {"_explicit_temporal_notice_request"}, {
                              "_detect_explicit_topic_or_entity": lambda x: None,
                              "academic_sessions": lambda x: [],
                          })["_explicit_temporal_notice_request"]
        self.assertEqual(f("Which notices were issued yesterday?"),
                         "yesterday_notices")
        self.assertEqual(f("What notices were published today?"), "today_notices")

    def test_q11_scoped_notice_still_not_global_time_query(self):
        f = offline_funcs("Module4/query_understanding.py",
                          {"_explicit_temporal_notice_request"}, {
                              "_detect_explicit_topic_or_entity":
                                  lambda text: "hostel" if "hostel" in text else None,
                              "academic_sessions": lambda x: [],
                          })["_explicit_temporal_notice_request"]
        self.assertIsNone(f("Which hostel notices were issued yesterday?"))

    def test_q41_natural_difference_triggers_comparison(self):
        fn = self._main("_is_comparison_query")["_is_comparison_query"]
        self.assertTrue(fn(
            "How do admission reporting deadlines differ for WBJEEB 2025 and 2026?"
        ))
        self.assertFalse(fn("Find a different WBJEE notice."))

    def test_q41_report_both_years_with_separate_sources(self):
        docs = [
            notice("old", "WBJEEB-2025 Document Verification and Admission Reporting"),
            notice("new", "WBJEEB-2026 Document Verification and Admission Reporting"),
        ]
        docs[0]["structured_data"]["important_dates"] = {"last_date": "11-09-2025"}
        docs[1]["structured_data"]["important_dates"] = {"last_date": "13-09-2026"}
        ret = import_retrieve_offline(docs)
        ns = self._main("_comparison_notice_answer", "_preferred_evidence_record")
        with patch.dict(sys.modules, {"retrieve": ret}):
            result = ns["_comparison_notice_answer"](
                "How do admission reporting deadlines differ for WBJEEB 2025 and 2026?",
                None,
            )
        self.assertIn("2025 —", result["answer"])
        self.assertIn("2026 —", result["answer"])
        self.assertIn("11-09-2025", result["answer"])
        self.assertIn("13-09-2026", result["answer"])
        self.assertIn("https://makautwb.ac.in/old.pdf", result["answer"])
        self.assertIn("https://makautwb.ac.in/new.pdf", result["answer"])
        self.assertEqual(len(result["records"]), 2)

    def test_q42_real_comparison_never_pairs_allotment_and_viswakarma(self):
        docs = [
            notice("allot", "Hostel Allotment Application AY 2026-27"),
            notice("close", "Hostel Closure during Durga Puja"),
            notice("viswa", "University Holiday on Viswakarma Puja"),
        ]
        ret = import_retrieve_offline(docs)
        ns = self._main("_compare_hostel_and_holiday")
        ns["display_summary"] = lambda record: ("summary", None)
        with patch.dict(sys.modules, {"retrieve": ret}):
            result = ns["_compare_hostel_and_holiday"](
                "Compare hostel closure and university holiday notices around Durga Puja",
                None,
            )
        self.assertIn("Hostel Closure", result["answer"])
        self.assertIn("No matching processed notice", result["answer"])
        self.assertNotIn("Allotment Application", result["answer"])
        self.assertNotIn("Viswakarma", result["answer"])
        self.assertEqual([r["notice_id"] for r in result["records"]], ["close"])

    def test_q23_multiple_admissions_requires_disambiguation(self):
        ns = self._main("_direct_fact_answer", "_preferred_evidence_record")
        docs = [
            notice("first", "B.Tech Admission Notice 2026"),
            notice("second", "M.Tech Admission Notice 2026"),
        ]
        parsed = types.SimpleNamespace(requested_field="fees")
        answer, selected = ns["_direct_fact_answer"](
            "Are both application fees and admission fees mentioned "
            "in the 2026 admission notice?", docs, parsed)
        self.assertIn("Which admission notice", answer)
        self.assertIn("https://makautwb.ac.in/first.pdf", answer)
        self.assertIn("https://makautwb.ac.in/second.pdf", answer)
        self.assertEqual(len(selected), 2)

    def test_q24_eligible_candidates_registration_not_criteria(self):
        ns = self._main("_field_answer", extra={
            "_plain": str,
        })
        r = notice(
            "generic", "Opening of JELET-2025 Registration",
        )
        r["structured_data"]["key_points"] = [
            "All eligible candidates must complete registration by 11 February."
        ]
        result = ns["_field_answer"](
            "Give me eligibility criteria for JELET 2025", r, "eligibility")
        self.assertIn("couldn't verify specific eligibility criteria", result)
        self.assertNotIn("Eligibility evidence extracted", result)

    def test_q26_category_certificate_not_assumed_eligibility(self):
        ns = self._main("_field_answer", extra={"_plain": str})
        r = notice("wbjee", "WBJEEB-2026 document verification")
        r["structured_data"]["key_points"] = [
            "Carry original OBC NCL and EWS certificates for document verification."
        ]
        result = ns["_field_answer"](
            "Are there reserved-category eligibility requirements in the "
            "WBJEE admission notice?", r, "eligibility")
        self.assertIn("cannot confirm separate reserved-category eligibility", result)


if __name__ == "__main__":
    unittest.main()
