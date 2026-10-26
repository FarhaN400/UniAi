"""Regression checks for the final incorrect-source batch and Render release guard.

These use synthetic records or mocked HTTP. Live MAKAUT PDF verification remains
necessary; successful status codes alone do not establish factual accuracy.
"""
import ast
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import unittest
from unittest.mock import patch

from test_academic_scope import import_retrieve_offline, notice

ROOT = Path(__file__).resolve().parents[1]


def import_runner():
    path = ROOT / "evaluation" / "run_50.py"
    spec = importlib.util.spec_from_file_location("uniai_eval_runner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, data):
        self.data = data
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, *args):
        return json.dumps(self.data).encode()


class ReleaseGuardTests(unittest.TestCase):
    def setUp(self):
        self.runner = import_runner()
        self.sha = "b0471a5a377459002baeb6f3d20fdf0060f328ba"

    def test_matching_render_deploy_allows_evaluation(self):
        with patch.object(self.runner.request, "urlopen",
                          return_value=FakeResponse({"revision": self.sha})):
            self.runner.verify_revision("https://backend.example", self.sha[:12])

    def test_stale_render_revision_fails_closed(self):
        with patch.object(self.runner.request, "urlopen",
                          return_value=FakeResponse({"revision": "abcd1234"})):
            with self.assertRaisesRegex(RuntimeError, "Wrong Render version"):
                self.runner.verify_revision("https://backend.example", self.sha[:9])

    def test_old_backend_missing_revision_fails_closed(self):
        with patch.object(self.runner.request, "urlopen",
                          return_value=FakeResponse({"status": "ok"})):
            with self.assertRaisesRegex(RuntimeError, "Wrong Render version"):
                self.runner.verify_revision("https://backend.example", self.sha[:9])

    def test_invalid_revision_rejected_before_network(self):
        with patch.object(self.runner.request, "urlopen") as call:
            with self.assertRaises(ValueError):
                self.runner.verify_revision("https://backend.example", "hello!")
            call.assert_not_called()

    def test_selected_ids_only_include_requested_questions(self):
        import csv
        import tempfile
        from pathlib import Path
        runner = self.runner
        def fake_urlopen(req, timeout):
            # POST requests return standard chat payloads.
            return FakeResponse({"answer": "No matching notice", "sources": []})
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "results.csv"
            with patch.object(runner.request, "urlopen", side_effect=fake_urlopen):
                with patch.object(runner.time, "sleep", return_value=None):
                    runner.execute("https://backend.example", output,
                                   delay_seconds=0, only_ids=["Q03", "Q17"])
            with output.open() as f:
                rows = list(csv.DictReader(f))
            self.assertEqual([r["id"] for r in rows], ["Q03", "Q17"])

    def test_invalid_question_ids_error_before_api_requests(self):
        runner = self.runner
        with patch.object(runner.request, "urlopen") as call:
            with self.assertRaisesRegex(ValueError, "Unknown question IDs"):
                runner.execute("https://backend.example",
                               Path("/tmp/not-created.csv"),
                               only_ids=["QZZ"])
            call.assert_not_called()

    def test_health_reports_public_commit_without_secrets(self):
        path = ROOT / "app.py"
        tree = ast.parse(path.read_text(encoding="utf8"))
        method = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                      and n.name == "health")
        from contextlib import nullcontext
        import time
        ns = {"os": os, "time": time, "_registry_lock": nullcontext(),
              "_cleanup_sessions": lambda *args: None, "session_store": {}}
        exec(compile(ast.Module(body=[method], type_ignores=[]),
                     str(path), "exec"), ns)
        with patch.dict(os.environ, {"RENDER_GIT_COMMIT": self.sha}):
            response = ns["health"]()
        self.assertEqual(response["revision"], self.sha)
        self.assertEqual(response["status"], "ok")
        self.assertNotIn("MONGO_URI", str(response))


class FinalCitationsTests(unittest.TestCase):
    def test_q03_hostel_rejects_refund_and_anti_ragging_even_if_upstream_returns_them(self):
        rows = [
            notice("hostel", "Hostel Closure during Durga Puja Festival"),
            notice("anti", "Constitution of Anti-Ragging Committee",
                   summary="Includes a hostel representative"),
            notice("refund", "Guidelines for Refund of Fees upon Student Withdrawal",
                   summary="Hostel fees mentioned in the footnotes"),
        ]
        retriever = import_retrieve_offline(rows)
        kept = retriever.enforce_source_scope("Show recent hostel notices.", rows)
        self.assertEqual([item["notice_id"] for item in kept], ["hostel"])

    def test_q17_generic_lateral_not_jelet_issue_date_even_with_exam_in_audience(self):
        rows = [
            notice("generic", "Opening Phase 1 Registration for B.Tech Lateral AY 2025-26",
                   audience="JELET-2025 candidates"),
            notice("jelet", "JELET-2025 admission reporting"),
        ]
        retriever = import_retrieve_offline(rows)
        kept = retriever.enforce_source_scope(
            "What is the official issue date of the JELET 2025 notice?", rows
        )
        self.assertEqual([x["notice_id"] for x in kept], ["jelet"])

    def test_q24_jelet_eligibility_rejects_lateral_registration(self):
        rows = [
            notice("generic", "Opening Phase 1 Registration for B.Tech Lateral",
                   audience="JELET 2025 candidates"),
            notice("specific", "JELET-2025 admission guidance"),
        ]
        retriever = import_retrieve_offline(rows)
        kept = retriever.enforce_source_scope("Give me eligibility criteria for JELET 2025.", rows)
        self.assertEqual([x["notice_id"] for x in kept], ["specific"])

    def test_q23_generic_admission_fee_cannot_be_hostel_or_refund(self):
        rows = [
            notice("hostel", "Hostel Allotment Application AY 2026-2027"),
            notice("refund", "Guidelines for Refund of Admission Fees"),
            notice("admission", "B.Tech Admission Notice 2026"),
        ]
        retriever = import_retrieve_offline(rows)
        kept = retriever.enforce_source_scope(
            "Are both application fees and admission fees mentioned in "
            "the 2026 admission notice?", rows
        )
        self.assertEqual([x["notice_id"] for x in kept], ["admission"])

    def test_explicit_hostel_fee_request_can_still_find_hostel(self):
        rows = [notice("hostel", "Hostel Allotment Application AY 2026-2027")]
        retriever = import_retrieve_offline(rows)
        kept = retriever.enforce_source_scope(
            "What fee is in the hostel allotment notice?", rows
        )
        self.assertEqual([x["notice_id"] for x in kept], ["hostel"])

    def test_generic_latest_notices_not_subject_filtered(self):
        rows = [
            notice("one", "Anti-Ragging Committee Order"),
            notice("two", "Hostel Allotment Application"),
        ]
        retriever = import_retrieve_offline(rows)
        kept = retriever.enforce_source_scope("Show the five latest MAKAUT notices.", rows)
        self.assertEqual(len(kept), 2)


if __name__ == "__main__":
    unittest.main()
