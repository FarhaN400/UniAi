"""Offline regression for Phase 2 overview claim merging (Python 3.9+).

Run from backend/: python3 test_phase2_overview_merge.py
The test calls answer_from_records with a fake LLM and real evidence.py.
It does not access MongoDB, Ollama or Pinecone.
"""
import ast
import importlib.util
import json
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
MOD = HERE / "Module4"


def load_evidence():
    spec = importlib.util.spec_from_file_location("phase2_evidence", MOD / "evidence.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_helpers():
    source = MOD / "main.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    funcs = {
        "_response_text", "_record_requires_both_sciences",
        "_eligibility_contradiction", "_apply_eligibility_guard",
        "_missing_notice_overview_facets", "_claim_covers_missing_facet",
        "_parse_claim_payload", "_render_supported_claims",
        "answer_from_records",
    }
    body = [x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name in funcs]
    ns = {"os": os, "re": re, "json": json}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(source), "exec"), ns)
    return ns


class DummyState:
    def __init__(self):
        self.turns = []

    def format_recent_history(self, max_turns=2):
        return ""

    def append_turn(self, question, content, records=None, active_notice=None):
        self.turns.append({"question": question, "content": content, "records": records or []})


class FakeChain:
    def __init__(self, first_claims, retry_claims):
        self.first_claims = first_claims
        self.retry_claims = retry_claims
        self.calls = []

    def invoke(self, values):
        self.calls.append(values)
        claims = self.first_claims if len(self.calls) == 1 else self.retry_claims
        return {"content": json.dumps({"claims": claims})}


def run():
    ev = load_evidence()
    ns = load_helpers()
    nid = "3272f6705ede6a9aa67cebab5db273359e3b9828c2820e6a9c6e8572de644488"
    pdf = "https://makautwb.ac.in/datas/users/0-in-house%20b.%20tech%20decentralize%20notice%202026.pdf"
    record = {
        "notice_id": nid,
        "title": "Vacant Seats for UG Courses in MAKAUT, WB - 2026-2027",
        "url": pdf,
        "structured_data": {
            "notice_type": "Admission",
            "title": "Vacant Seats for UG Courses in MAKAUT, WB - 2026-2027",
            "issue_date": "14-10-2026",
            "important_dates": {"start_date": "14-10-2026", "last_date": "27-10-2026"},
            "action_required": (
                "Interested candidates must apply online via a provided link between "
                "14-10-2026 and 27-10-2026, and report to Haringhata Campus "
                "Administrative Building, Room 103 on 28-10-2026 with original documents."
            ),
            "key_points": [
                "Vacant B.Tech courses: Computer Science and Engineering, Information "
                "Technology, Electronics Engineering (VLSI Design and Technology), "
                "and Industrial Engineering.",
                "Eligibility: Physics and Mathematics compulsory at 10+2, plus one "
                "approved additional subject, minimum 45% (40% reserved) in the "
                "specified three subjects taken together.",
                "Merit list and reporting on 28-10-2026 at Haringhata Campus, "
                "Administrative Building, Room 103.",
                "Documents: 10+2 mark sheet, DOB proof, applicable caste certificate, "
                "Aadhaar card and domicile certificate, with originals and photocopies.",
            ],
        },
    }
    q = "Explain the MAKAUT vacant B.Tech seats notice dated 14 October 2026."
    context, evidence, byid = ev.build_evidence_bundle(
        [record], q, lambda records, question: "", lambda *args, **kwargs: [],
    )
    find_ref = lambda snippet: next(k for k, v in evidence.items() if snippet in v["text"])
    title_ref = find_ref("title:")
    dates_ref = find_ref("action_required:")
    facts_ref = find_ref("key_points:")

    course_claim = {
        "text": "Vacant seats are available in B.Tech courses: Computer Science and Engineering, Information Technology, Electronics Engineering (VLSI Design and Technology), and Industrial Engineering for the 2026-2027 academic session.",
        "notice_ids": [nid], "evidence_refs": [title_ref, facts_ref],
    }
    app_claim = {
        "text": "Interested candidates must apply online between 14-10-2026 and 27-10-2026.",
        "notice_ids": [nid], "evidence_refs": [dates_ref],
    }
    eligibility_claim = {
        "text": "Eligibility requires Physics and Mathematics as compulsory subjects, plus one additional subject from the approved list, with 45% marks (40% reserved) in the specified three subjects taken together.",
        "notice_ids": [nid], "evidence_refs": [facts_ref],
    }
    report_claim = {
        "text": "Candidates must report to Haringhata Campus, Administrative Building, Room 103, on 28-10-2026.",
        "notice_ids": [nid], "evidence_refs": [dates_ref, facts_ref],
    }
    documents_claim = {
        "text": "Required documents include 10+2 mark sheet, DOB proof, caste certificate where applicable, Aadhaar card and domicile certificate, with originals and photocopies.",
        "notice_ids": [nid], "evidence_refs": [facts_ref],
    }
    first = [course_claim, app_claim]
    retry = [course_claim, eligibility_claim, app_claim, report_claim, documents_claim]

    # Assert each proposed claim has properly supported evidence first.
    assert len(ev.validate_claims(first + retry, evidence, byid, debug=True)) == 7

    chain = FakeChain(first, retry)
    state = DummyState()
    ns.update({
        "state": DummyState(),
        "rag_chain": chain,
        "build_evidence_bundle": ev.build_evidence_bundle,
        "build_context_string": lambda records, question: "",
        "extract_relevant_snippets": lambda *args, **kwargs: [],
        "validate_claims": ev.validate_claims,
        "NO_RESULTS_MESSAGE": "I could not find this information in the available university notices.",
    })
    answer = ns["answer_from_records"](q, [record], active_notice=record, current_state=state)
    assert len(chain.calls) == 2, f"Expected exactly one retry, received {len(chain.calls) - 1}"
    for expected in (
        "Computer Science and Engineering", "Information Technology",
        "Physics and Mathematics as compulsory", "45%", "40%",
        "14-10-2026", "27-10-2026", "Room 103", "28-10-2026",
        "Aadhaar card", "domicile certificate", "photocopies",
    ):
        assert expected in answer, f"Missing final answer detail: {expected}"
    assert answer.count("Vacant seats are available") == 1, "Course facts duplicated"
    assert answer.count("must apply online") == 1, "Application details duplicated"
    assert len(state.turns) == 1 and len(state.turns[0]["records"]) == 1
    assert state.turns[0]["records"][0]["url"] == pdf
    assert not ns["_missing_notice_overview_facets"](q, byid, evidence, retry)
    print("PASS: initial courses/application kept; eligibility, reporting, and documents merged")
    print("PASS: no duplicate facts, exactly one retry, correct single-notice source")


if __name__ == "__main__":
    run()
