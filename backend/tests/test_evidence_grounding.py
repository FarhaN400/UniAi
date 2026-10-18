import json
import os
import sys
import types
import unittest
from unittest.mock import patch


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def _install_backend_stubs():
    class DummyModel:
        def __init__(self, **kwargs):
            pass

    class DummyPrompt:
        def __or__(self, model):
            return DummyChain()

    class DummyChain:
        def invoke(self, inputs):
            raise AssertionError("Tests must provide a mocked model response.")

    prompt_module = types.ModuleType("Module4.prompt")
    prompt_module.rag_prompt = DummyPrompt()
    query_module = types.ModuleType("Module4.query_understanding")
    query_module.understand_query = lambda *args, **kwargs: None
    query_module.QueryUnderstandingResult = object
    query_module.explicitly_changes_notice_topic = lambda *args, **kwargs: False

    retrieve_module = types.ModuleType("retrieve")
    retrieve_module.build_context_string = lambda records, question=None: "test context"
    retrieve_module.extract_relevant_snippets = lambda *args, **kwargs: []
    retrieve_module.retrieve_context = lambda *args, **kwargs: []
    retrieve_module.retrieve_topic_notices = lambda *args, **kwargs: []

    ollama_module = types.ModuleType("langchain_ollama")
    ollama_module.ChatOllama = DummyModel
    sys.modules.setdefault("langchain_ollama", ollama_module)
    sys.modules["Module4.prompt"] = prompt_module
    sys.modules["Module4.query_understanding"] = query_module
    sys.modules["retrieve"] = retrieve_module


_install_backend_stubs()

from Module4 import main
from Module4.conversation_state import ConversationState
from Module4.evidence import (
    build_evidence_bundle,
    filter_explicit_notice_scope,
    sources_from_records,
    validate_claims,
)


def _notice(notice_id, title, issue_date, fields, url):
    return {
        "notice_id": notice_id,
        "title": title,
        "url": url,
        "raw_text": "",
        "structured_data": {
            "title": title,
            "issue_date": issue_date,
            **fields,
        },
    }


class EvidenceGroundingTests(unittest.TestCase):
    def setUp(self):
        self.october_notice = _notice(
            "vacant-october-2026",
            "MAKAUT vacant B.Tech seats notice",
            "14-10-2026",
            {
                "important_dates": {
                    "application_closing_date": "27 October 2026",
                    "merit_list_and_reporting": "28 October 2026",
                },
                "summary": "Vacant B.Tech seat application and reporting details.",
            },
            "https://makautwb.ac.in/datas/users/0-vacant-oct-2026.pdf",
        )
        self.january_notice = _notice(
            "admission-january-2026",
            "MAKAUT January admission notice",
            "12-01-2026",
            {
                "important_dates": {
                    "application_closing_date": "20 January 2026",
                },
                "summary": "January admission schedule.",
            },
            "https://makautwb.ac.in/datas/users/0-january-2026.pdf",
        )
        self.first_round = _notice(
            "wbjeeb-first-round-2025",
            "WBJEEB-2025 first-round document verification",
            None,
            {
                "admission_round": "First round",
            },
            "https://makautwb.ac.in/datas/users/0-wbjee_2526.pdf",
        )
        self.second_round = _notice(
            "wbjeeb-second-round-2025",
            "WBJEEB-2025 second-round document verification",
            "08-09-2025",
            {
                "admission_round": "Second round",
                "reporting_dates": "9–11 September 2025",
                "reporting_time": "12 noon–4 PM",
                "location": "MAKAUT Haringhata Main Campus",
            },
            "https://makautwb.ac.in/datas/users/0-wbjee_2nd_2526.pdf",
        )

    def _answer_payload(self, claims):
        return json.dumps({"claims": claims})

    def _citation(self, notice_id, reference, quote):
        return {
            "notice_id": notice_id,
            "reference": reference,
            "quote": quote,
        }

    def _reference(self, evidence, notice_id, contained_text):
        return next(
            reference
            for reference, fact in evidence.items()
            if fact["notice_id"] == notice_id and contained_text in fact["text"]
        )

    def test_exact_date_selects_october_notice_and_keeps_its_facts(self):
        question = "Explain the MAKAUT vacant B.Tech seats notice dated 14 October 2026."
        selected, found_date, ambiguous = main.select_notice_evidence(
            question,
            [self.january_notice, self.october_notice],
        )
        self.assertTrue(found_date)
        self.assertFalse(ambiguous)
        self.assertEqual([self.october_notice], selected)

        _, evidence, _ = build_evidence_bundle(
            selected,
            question,
            lambda records, question=None: "notice context",
            lambda *args, **kwargs: [],
        )
        closing_date_ref = self._reference(
            evidence, "vacant-october-2026", "27 October 2026"
        )
        reporting_date_ref = self._reference(
            evidence, "vacant-october-2026", "28 October 2026"
        )
        claims = [
            {
                "text": "The application closing date is 27 October 2026.",
                "notice_ids": ["vacant-october-2026"],
                "evidence": [self._citation(
                    "vacant-october-2026",
                    closing_date_ref,
                    "important_dates.application_closing_date: 27 October 2026",
                )],
            },
            {
                "text": "The merit list and reporting are on 28 October 2026.",
                "notice_ids": ["vacant-october-2026"],
                "evidence": [self._citation(
                    "vacant-october-2026",
                    reporting_date_ref,
                    "important_dates.merit_list_and_reporting: 28 October 2026",
                )],
            },
        ]
        with patch.object(
            main.rag_chain,
            "invoke",
            return_value=self._answer_payload(claims),
        ):
            state = ConversationState()
            answer = main.answer_from_records(
                question,
                selected,
                active_notice=selected[0],
                current_state=state,
            )

        self.assertIn("27 October 2026", answer)
        self.assertIn("28 October 2026", answer)
        self.assertNotIn("January", answer)
        self.assertIn(self.october_notice["url"], answer)
        self.assertEqual(
            ["vacant-october-2026"],
            [record["notice_id"] for record in state.get_last_answer_records()],
        )

    def test_second_round_scope_excludes_other_year_and_round(self):
        old_second_round = _notice(
            "wbjeeb-second-round-2024",
            "WBJEEB-2024 second-round document verification",
            "13-10-2024",
            {"admission_round": "Second round"},
            "https://makautwb.ac.in/old.pdf",
        )
        selected = filter_explicit_notice_scope(
            "WBJEEB-2025 second-round document verification",
            [self.first_round, old_second_round, self.second_round],
        )
        self.assertEqual([self.second_round], selected)

        _, evidence, _ = build_evidence_bundle(
            selected,
            "What are the reporting dates and times for WBJEEB-2025 second-round verification?",
            lambda records, question=None: "notice context",
            lambda *args, **kwargs: [],
        )
        claims = []
        for fact, text in (
            (
                "reporting_dates: 9–11 September 2025",
                "Reporting dates are 9–11 September 2025.",
            ),
            (
                "reporting_time: 12 noon–4 PM",
                "Reporting time is 12 noon–4 PM.",
            ),
            (
                "MAKAUT Haringhata Main Campus",
                "The location is MAKAUT Haringhata Main Campus.",
            ),
        ):
            reference = self._reference(
                evidence, "wbjeeb-second-round-2025", fact
            )
            claims.append({
                "text": text,
                "notice_ids": ["wbjeeb-second-round-2025"],
                "evidence": [self._citation(
                    "wbjeeb-second-round-2025",
                    reference,
                    fact,
                )],
            })
        with patch.object(main.rag_chain, "invoke", return_value=self._answer_payload(claims)):
            state = ConversationState()
            answer = main.answer_from_records(
                "What are the reporting dates and times for WBJEEB-2025 second-round verification?",
                selected,
                current_state=state,
            )

        self.assertIn("9–11 September 2025", answer)
        self.assertIn("12 noon–4 PM", answer)
        self.assertIn("Haringhata Main Campus", answer)
        self.assertNotIn("13–15 October 2024", answer)
        self.assertIn(self.second_round["url"], answer)
        self.assertEqual(
            ["wbjeeb-second-round-2025"],
            [record["notice_id"] for record in state.get_last_answer_records()],
        )

    def test_comparison_claims_remain_attached_to_their_own_notice_ids(self):
        context, evidence, records_by_id = build_evidence_bundle(
            [self.first_round, self.second_round],
            "Compare the first-round and second-round verification requirements.",
            lambda records, question=None: "mock notice text",
            lambda *args, **kwargs: [],
        )
        self.assertIn("NOTICE_ID: wbjeeb-first-round-2025", context)
        self.assertIn("NOTICE_ID: wbjeeb-second-round-2025", context)
        first_ref = next(
            ref for ref, fact in evidence.items()
            if fact["notice_id"] == "wbjeeb-first-round-2025"
            and "admission_round: First round" in fact["text"]
        )
        second_round_ref = self._reference(
            evidence,
            "wbjeeb-second-round-2025",
            "admission_round: Second round",
        )
        second_date_ref = self._reference(
            evidence,
            "wbjeeb-second-round-2025",
            "reporting_dates: 9–11 September 2025",
        )
        claims = [
            {
                "text": "This source is identified as the first round.",
                "notice_ids": ["wbjeeb-first-round-2025"],
                "evidence": [self._citation(
                    "wbjeeb-first-round-2025",
                    first_ref,
                    "admission_round: First round",
                )],
            },
            {
                "text": "Second-round reporting is 9–11 September 2025.",
                "notice_ids": ["wbjeeb-second-round-2025"],
                "evidence": [
                    self._citation(
                        "wbjeeb-second-round-2025",
                        second_round_ref,
                        "admission_round: Second round",
                    ),
                    self._citation(
                        "wbjeeb-second-round-2025",
                        second_date_ref,
                        "reporting_dates: 9–11 September 2025",
                    ),
                ],
            },
        ]
        accepted = validate_claims(claims, evidence, records_by_id)
        self.assertEqual(2, len(accepted))
        self.assertEqual(
            ["wbjeeb-first-round-2025", "wbjeeb-second-round-2025"],
            [claim["notice_ids"][0] for claim in accepted],
        )
        with patch.object(
            main.rag_chain,
            "invoke",
            return_value=self._answer_payload(claims),
        ):
            state = ConversationState()
            answer = main.answer_from_records(
                "Compare the first-round and second-round verification requirements.",
                [self.first_round, self.second_round],
                current_state=state,
            )
        self.assertIn(self.first_round["url"], answer)
        self.assertIn(self.second_round["url"], answer)
        self.assertEqual(
            ["wbjeeb-first-round-2025", "wbjeeb-second-round-2025"],
            [record["notice_id"] for record in state.get_last_answer_records()],
        )

    def test_missing_fee_amount_is_represented_without_inventing_a_value(self):
        question = (
            "What is the application fee in the 14 October 2026 vacant "
            "B.Tech seats notice?"
        )
        selected, found_date, ambiguous = main.select_notice_evidence(
            question,
            [self.january_notice, self.october_notice],
        )
        self.assertTrue(found_date)
        self.assertFalse(ambiguous)
        self.assertEqual([self.october_notice], selected)

        record = _notice(
            "vacant-fee",
            "MAKAUT vacant B.Tech seats notice",
            "14-10-2026",
            {
                "fees": {"amount": None, "currency": None},
                "action_required": "Pay the applicable admission fee online.",
            },
            "https://makautwb.ac.in/datas/users/0-vacant-fee.pdf",
        )
        record["raw_text"] = (
            "Candidates must be prepared for online payment of admission fees. "
            "The applicable fee can be checked on the official MAKAUT "
            "fee-information page."
        )
        _, evidence, records_by_id = build_evidence_bundle(
            [record],
            "What is the application fee?",
            lambda records, question=None: "notice text",
            lambda raw_text, *args, **kwargs: [raw_text],
        )
        fee_ref = self._reference(
            evidence,
            "vacant-fee",
            "application fee amount: Not specified in structured data",
        )
        excerpt_ref = self._reference(
            evidence, "vacant-fee", "online payment of admission fees"
        )
        claims = [
            {
                "text": "The supplied notice record does not specify an application fee amount.",
                "notice_ids": ["vacant-fee"],
                "evidence": [self._citation(
                    "vacant-fee",
                    fee_ref,
                    "application fee amount: Not specified in structured data",
                )],
            },
            {
                "text": "Candidates should be prepared for online payment of admission fees.",
                "notice_ids": ["vacant-fee"],
                "evidence": [self._citation(
                    "vacant-fee",
                    excerpt_ref,
                    "online payment of admission fees",
                )],
            },
            {
                "text": "The applicable fee is listed on the official MAKAUT fee-information page.",
                "notice_ids": ["vacant-fee"],
                "evidence": [self._citation(
                    "vacant-fee",
                    excerpt_ref,
                    "official MAKAUT fee-information page",
                )],
            },
        ]
        with patch.object(
            main,
            "extract_relevant_snippets",
            side_effect=lambda raw_text, *args, **kwargs: [raw_text],
        ), patch.object(
            main.rag_chain,
            "invoke",
            return_value=self._answer_payload(claims),
        ):
            state = ConversationState()
            answer = main.answer_from_records(
                question,
                [record],
                active_notice=record,
                current_state=state,
            )
        self.assertIn("does not specify an application fee amount", answer)
        self.assertIn("online payment of admission fees", answer)
        self.assertIn("fee-information page", answer)
        self.assertNotRegex(
            answer,
            r"application fee amount(?:\s+is|:)?\s*\d",
        )
        self.assertEqual(
            [record["url"]],
            [source["url"] for source in sources_from_records(
                state.get_last_answer_records()
            )],
        )

    def test_unverifiable_claim_is_removed_and_has_no_supporting_source(self):
        _, evidence, records_by_id = build_evidence_bundle(
            [self.october_notice],
            "What guaranteed placement package is mentioned?",
            lambda records, question=None: "notice text",
            lambda *args, **kwargs: [],
        )
        summary_ref = self._reference(
            evidence,
            "vacant-october-2026",
            "summary:",
        )
        unsupported = [{
            "text": "The notice guarantees a 15 LPA package.",
            "notice_ids": ["vacant-october-2026"],
            "evidence": [self._citation(
                "vacant-october-2026",
                summary_ref,
                "Vacant B.Tech seat application and reporting details.",
            )],
        }]
        self.assertEqual([], validate_claims(unsupported, evidence, records_by_id))
        self.assertEqual([], sources_from_records([]))
        state = ConversationState()
        state.append_turn(
            "Explain the notice.",
            "Earlier supported answer.",
            records=[self.october_notice],
        )
        with patch.object(
            main.rag_chain,
            "invoke",
            return_value=self._answer_payload(unsupported),
        ):
            answer = main.answer_from_records(
                "What guaranteed placement package is mentioned?",
                [self.october_notice],
                current_state=state,
            )
        self.assertEqual(main.NO_RESULTS_MESSAGE, answer)
        self.assertEqual([], state.get_last_answer_records())

    def test_claim_cannot_mix_facts_from_two_notices(self):
        _, evidence, records_by_id = build_evidence_bundle(
            [self.first_round, self.second_round],
            "Compare verification notices.",
            lambda records, question=None: "notice text",
            lambda *args, **kwargs: [],
        )
        second_round_ref = self._reference(
            evidence, "wbjeeb-second-round-2025", "9–11 September 2025"
        )
        mixed_claim = {
            "text": "Both rounds report on 9–11 September 2025.",
            "notice_ids": [
                "wbjeeb-first-round-2025",
                "wbjeeb-second-round-2025",
            ],
            "evidence": [self._citation(
                "wbjeeb-second-round-2025",
                second_round_ref,
                "9–11 September 2025",
            )],
        }
        self.assertEqual(
            [],
            validate_claims([mixed_claim], evidence, records_by_id),
        )

    def test_claim_cannot_change_month_while_reusing_supported_date_numbers(self):
        _, evidence, records_by_id = build_evidence_bundle(
            [self.second_round],
            "What are the second-round reporting dates?",
            lambda records, question=None: "notice text",
            lambda *args, **kwargs: [],
        )
        reference = self._reference(
            evidence, "wbjeeb-second-round-2025", "9–11 September 2025"
        )
        wrong_month = {
            "text": "Reporting dates are 9–11 October 2025.",
            "notice_ids": ["wbjeeb-second-round-2025"],
            "evidence": [self._citation(
                "wbjeeb-second-round-2025",
                reference,
                "reporting_dates: 9–11 September 2025",
            )],
        }
        self.assertEqual(
            [],
            validate_claims([wrong_month], evidence, records_by_id),
        )

    def test_additional_urls_must_be_evidenced_and_are_labeled_separately(self):
        record = dict(self.october_notice)
        record["raw_text"] = (
            "Official fee information is available at "
            "https://makautwb.ac.in/fees"
        )
        excerpt = (
            "Official fee information is available at "
            "https://makautwb.ac.in/fees"
        )
        _, evidence, records_by_id = build_evidence_bundle(
            [record],
            "What is the fee?",
            lambda records, question=None: "notice text",
            lambda *args, **kwargs: [excerpt],
        )
        excerpt_ref = self._reference(
            evidence, "vacant-october-2026", excerpt
        )
        claim = {
            "text": f"Fee information: {excerpt}",
            "notice_ids": ["vacant-october-2026"],
            "evidence": [self._citation(
                "vacant-october-2026",
                excerpt_ref,
                excerpt,
            )],
        }
        accepted = validate_claims([claim], evidence, records_by_id)
        self.assertEqual(1, len(accepted))
        answer, _ = main._render_supported_claims(accepted, records_by_id)
        self.assertIn("not the primary supporting PDF", answer)

        fabricated_url_claim = dict(claim)
        fabricated_url_claim["text"] = (
            "Fee information: https://makautwb.ac.in/fabricated"
        )
        self.assertEqual(
            [],
            validate_claims([fabricated_url_claim], evidence, records_by_id),
        )

    def test_follow_up_keeps_only_the_active_notice_source(self):
        state = ConversationState()
        state.append_turn(
            "Explain the second-round notice.",
            "Second-round report date.",
            records=[self.second_round],
            active_notice=self.second_round,
        )
        _, evidence, _ = build_evidence_bundle(
            [self.second_round],
            "Where does reporting take place?",
            lambda records, question=None: "notice text",
            lambda *args, **kwargs: [],
        )
        location_ref = self._reference(
            evidence, "wbjeeb-second-round-2025", "MAKAUT Haringhata Main Campus"
        )
        with patch.object(main.rag_chain, "invoke", return_value=self._answer_payload([
            {
                "text": "The location is MAKAUT Haringhata Main Campus.",
                "notice_ids": ["wbjeeb-second-round-2025"],
                "evidence": [self._citation(
                    "wbjeeb-second-round-2025",
                    location_ref,
                    "MAKAUT Haringhata Main Campus",
                )],
            }
        ])):
            answer = main.answer_from_records(
                "Where does reporting take place?",
                [self.second_round],
                active_notice=self.second_round,
                current_state=state,
            )

        self.assertIn("Haringhata Main Campus", answer)
        self.assertEqual(
            ["wbjeeb-second-round-2025"],
            [record["notice_id"] for record in state.get_last_answer_records()],
        )

        state.append_turn("Thanks", "You're welcome.")
        self.assertEqual([], state.get_last_answer_records())
        self.assertEqual(
            ["wbjeeb-second-round-2025"],
            [record["notice_id"] for record in state.get_last_notice_records()],
        )

    def test_sources_are_deduplicated_and_use_only_supporting_records(self):
        sources = sources_from_records([
            self.second_round,
            dict(self.second_round),
            self.first_round,
        ])
        self.assertEqual(2, len(sources))
        self.assertEqual(self.second_round["url"], sources[0]["url"])
        self.assertEqual(self.first_round["url"], sources[1]["url"])
        self.assertEqual("08-09-2025", sources[0]["date"])
        missing_id = dict(self.second_round)
        missing_id.pop("notice_id")
        self.assertEqual([], sources_from_records([missing_id]))


if __name__ == "__main__":
    unittest.main()
