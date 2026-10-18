"""Offline Phase 2 regression tests. Run from backend/ with Python 3.9+.

This test loads main.py helpers without importing LangChain/Ollama, then uses
mocked model outputs. It tests logic, not the live external services.
"""
import ast
import importlib.util
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE4 = HERE / "Module4" if (HERE / "Module4" / "evidence.py").exists() else HERE

def load_evidence():
    spec = importlib.util.spec_from_file_location("phase2_evidence", MODULE4 / "evidence.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_main_helpers():
    source = (MODULE4 / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {
        "_response_text", "_record_requires_both_sciences",
        "_eligibility_contradiction", "_apply_eligibility_guard",
        "_missing_notice_overview_facets", "_claim_covers_missing_facet",
        "_parse_claim_payload", "_render_supported_claims", "answer_from_records",
    }
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    namespace = {"re": re, "json": json, "os": __import__("os")}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(MODULE4 / "main.py"), "exec"), namespace)
    return namespace


def run():
    evidence_mod = load_evidence()
    functions = load_main_helpers()
    nid = "3272f6705ede6a9aa67cebab5db273359e3b9828c2820e6a9c6e8572de644488"
    record = {
        "notice_id": nid,
        "title": "Vacant Seats for UG Courses in MAKAUT, WB - 2026-2027",
        "url": "https://makautwb.ac.in/datas/users/0-in-house%20b.%20tech%20decentralize%20notice%202026.pdf",
        "structured_data": {
            "notice_type": "Admission",
            "title": "Vacant Seats for UG Courses in MAKAUT, WB - 2026-2027",
            "reference_no": "MAKAUT/REG-ADM/NOTICE/2026/607",
            "issue_date": "14-10-2026",
            "important_dates": {"start_date": "14-10-2026", "last_date": "27-10-2026"},
            "action_required": (
                "Apply via https://forms.gle/ZoiTxZccmpK97RLS9 between 14-10-2026 "
                "and 27-10-2026; report with documents on 28-10-2026 at Haringhata Campus."
            ),
            "key_points": [
                "Vacant seats available in B.Tech courses: Computer Science and Engineering, "
                "Information Technology, Electronics Engineering (VLSI Design and Technology), "
                "and Industrial Engineering.",
                "Eligibility: Physics and Mathematics mandatory at 10+2, plus one permitted "
                "additional subject. Minimum 45% (40% for reserved category) in the "
                "specified subjects taken together.",
                "Documents: Class 12 marksheet, date of birth proof, applicable caste "
                "certificate, Aadhaar and domicile certificate (originals and photocopies).",
            ],
        },
        "raw_text": "Mandatory courses at 10 + 2 level: Physics, Maths. For remaining single course select any permitted course.",
    }
    records = [record]
    question = "Explain the MAKAUT vacant B.Tech seats notice dated 14 October 2026."
    context, refs, byid = evidence_mod.build_evidence_bundle(
        records, question, lambda records, question: "", lambda *args, **kwargs: [],
    )
    key_ref = next(k for k, v in refs.items() if "key_points:" in v["text"])
    title_ref = next(k for k, v in refs.items() if "title:" in v["text"])
    action_ref = next(k for k, v in refs.items() if "action_required:" in v["text"])

    incorrect = {
        "text": (
            "Vacant B.Tech seats for the 2026-2027 academic session require "
            "Physics, Mathematics, or other relevant subjects and 45% aggregate "
            "(40% for reserved candidates)."
        ),
        "notice_ids": [nid], "evidence_refs": [title_ref, key_ref],
    }
    # The old lexical validator would accept the AND-to-OR contradiction when
    # all numbers were cited. The new guard must reject that claim.
    assert len(evidence_mod.validate_claims([incorrect], refs, byid)) == 1
    assert not functions["_apply_eligibility_guard"]([incorrect], byid)

    allowed = {
        "text": (
            "Physics and Mathematics are mandatory at 10+2, with one additional "
            "permitted subject; at least 45% (40% for reserved category) is required "
            "in the specified subjects taken together."
        ),
        "notice_ids": [nid], "evidence_refs": [key_ref],
    }
    assert len(evidence_mod.validate_claims([allowed], refs, byid)) == 1
    assert len(functions["_apply_eligibility_guard"]([allowed], byid)) == 1
    assert not evidence_mod.validate_claims([
        {**allowed, "text": "The minimum is 99% in those subjects."}
    ], refs, byid)

    class DummyState:
        def __init__(self):
            self.turns = []
        def format_recent_history(self, max_turns=2):
            return ""
        def append_turn(self, question, content, records=None, active_notice=None):
            self.turns.append({"question": question, "answer": content, "records": records or []})

    class FakeChain:
        def __init__(self):
            self.calls = []
        def invoke(self, prompt_vars):
            self.calls.append(prompt_vars)
            if len(self.calls) == 1:
                return {"content": json.dumps({"claims": [
                    incorrect,
                    {
                        "text": "Apply online from 14-10-2026 to 27-10-2026.",
                        "notice_ids": [nid], "evidence_refs": [action_ref],
                    },
                ]})}
            return {"content": json.dumps({"claims": [
                {
                    "text": (
                        "Vacant B.Tech courses for the 2026-2027 academic session "
                        "include Computer Science and Engineering, Information Technology, "
                        "Electronics Engineering (VLSI Design and Technology), and Industrial Engineering."
                    ),
                    "notice_ids": [nid], "evidence_refs": [title_ref, key_ref],
                },
                allowed,
            ]})}

    chain = FakeChain()
    functions.update({
        "state": DummyState(), "rag_chain": chain,
        "build_evidence_bundle": evidence_mod.build_evidence_bundle,
        "build_context_string": lambda records, question: "",
        "extract_relevant_snippets": lambda *args, **kwargs: [],
        "validate_claims": evidence_mod.validate_claims,
        "NO_RESULTS_MESSAGE": "I could not find this information in the available university notices.",
    })
    output = functions["answer_from_records"](
        question, records, active_notice=record, current_state=DummyState(),
    )
    assert len(chain.calls) == 2, f"Expected exactly 1 retry, got {len(chain.calls) - 1}"
    assert "Computer Science and Engineering" in output
    assert "Information Technology" in output
    assert "Physics and Mathematics are mandatory" in output
    assert "specified subjects taken together" in output
    assert "or other relevant subjects" not in output
    assert "14-10-2026 to 27-10-2026" in output
    assert record["url"] in output
    print("PASS: unsupported OR eligibility blocked; overview repair includes courses and correct AND eligibility")
    print("PASS: initial supported dates retained; no invented 99% marks; exactly one retry")

if __name__ == "__main__":
    run()
