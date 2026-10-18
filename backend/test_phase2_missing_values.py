"""Offline tests for Phase 2 missing amount guidance. Python 3.9+.

Run from backend/: python3 test_phase2_missing_values.py
No Pinecone / MongoDB / Ollama required.
"""
import ast
import importlib.util
import json
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
MOD = HERE / "Module4"

spec = importlib.util.spec_from_file_location("test_evidence", MOD / "evidence.py")
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)

notice_id = "3272f6705ede6a9aa67cebab5db273359e3b9828c2820e6a9c6e8572de644488"
pdf = "https://makautwb.ac.in/datas/users/0-in-house%20b.%20tech%20decentralize%20notice%202026.pdf"
question = "What is the application fee mentioned in the MAKAUT vacant B.Tech seats notice dated 14 October 2026?"
record = {
    "notice_id": notice_id,
    "title": "In-House B.Tech Admission Decentralize Admission Notice 2026-27",
    "url": pdf,
    "structured_data": {
        "notice_type": "Admission",
        "title": "Vacant Seats for UG Courses in MAKAUT, WB - 2026-2027",
        "issue_date": "14-10-2026",
        "fees": {"amount": None, "currency": None},
        "important_dates": {"start_date": "14-10-2026", "last_date": "27-10-2026"},
        "key_points": [
            "Application online between 14-10-2026 and 27-10-2026.",
            "Admission fee details available at https://makautwb.ac.in/page.php?id=220.",
        ],
    },
}

# The actual requested notice gives a related admission-fee URL, not a
# verified application-fee amount. Neither 220 (URL) nor the date is a fee.
text = ev.missing_amount_guidance(question, record)
assert text is not None and "couldn't find an application-fee amount" in text
assert "https://makautwb.ac.in/page.php?id=220" in text
assert "admission-fee" in text
assert "₹" not in text and "Rs." not in text

# Use no external URL when a notice only cites a different site or the URL
# appears in unrelated data.
unknown = {**record, "structured_data": {**record["structured_data"],
    "key_points": ["Admission fee details: https://fake.example/pay"]}}
assert "fake.example" not in ev.missing_amount_guidance(question, unknown)

# Never suppress a document that actually contains an application-fee amount.
with_fee = {**record, "raw_text": "Application fee: Rs. 500 (non-refundable)."}
assert ev.missing_amount_guidance(question, with_fee) is None
with_structured_fee = {**record, "structured_data": {**record["structured_data"],
    "fees": {"amount": 500, "currency": "INR"}}}
assert ev.missing_amount_guidance(question, with_structured_fee) is None

# Ordinary unrelated questions must remain on normal LLM generation.
assert ev.missing_amount_guidance("What are the admission deadlines?", record) is None

# Guaranteed placement package query receives a cautious missing-value
# response without an invented package or source.
placement_q = "What guaranteed placement package is mentioned in that notice?"
package_text = ev.missing_amount_guidance(placement_q, record)
assert package_text is not None and "couldn't find" in package_text
assert ev.missing_amount_guidance(placement_q, {
    **record, "raw_text": "Guaranteed placement package: ₹12 LPA."
}) is None

# Run answer_from_records with an LLM that must NEVER be called in missing
# amount path. Ensure state persists the *original notice* for FastAPI sources.
source = MOD / "main.py"
tree = ast.parse(source.read_text(encoding="utf-8"))
names = {
    "answer_from_records", "_render_supported_claims", "_response_text",
    "_missing_notice_overview_facets", "_claim_covers_missing_facet",
    "_eligibility_contradiction", "_apply_eligibility_guard",
    "_record_requires_both_sciences", "_parse_claim_payload",
}
body = [node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names]
ns = {"re": re, "os": os, "json": json}
exec(compile(ast.Module(body=body, type_ignores=[]), str(source), "exec"), ns)

class DummyState:
    def __init__(self):
        self.turns = []

    def append_turn(self, question, content, records=None, active_notice=None):
        self.turns.append({"content": content, "records": records,
                           "active_notice": active_notice})

    def format_recent_history(self, max_turns=2):
        return ""

class NeverCallLLM:
    def invoke(self, _):
        raise AssertionError("Missing-value answer should not require Ollama")

st = DummyState()
ns.update({
    "state": DummyState(),
    "rag_chain": NeverCallLLM(),
    "missing_amount_guidance": ev.missing_amount_guidance,
    "build_evidence_bundle": ev.build_evidence_bundle,
    "build_context_string": lambda records, question: "",
    "extract_relevant_snippets": lambda *args, **kwargs: [],
    "validate_claims": ev.validate_claims,
    "NO_RESULTS_MESSAGE": "I could not find this information in the available university notices.",
})
answer = ns["answer_from_records"](question, [record], active_notice=record, current_state=st)
assert "couldn't find an application-fee amount" in answer
assert "page.php?id=220" in answer
assert pdf in answer
assert len(st.turns) == 1 and st.turns[0]["records"] == [record]
assert st.turns[0]["active_notice"] == record
assert ev.sources_from_records(st.turns[0]["records"]) == [{
    "title": record["structured_data"]["title"], "url": pdf, "date": "14-10-2026"
}]

# Python syntax and LangChain prompt-format variables remain intact.
tmpl = (MOD / "prompt.py").read_text(encoding="utf-8")
for item in ("{context}", "{history}", "{question}", "evidence_refs"):
    assert item in tmpl
print("PASS: Test 4 returns cautious fee guidance and official admission-fee URL")
print("PASS: original notice retained; FastAPI sources remain correct; no Ollama needed")
print("PASS: real fee amounts bypass missing-value fallback; unsafe URLs excluded")
print("PASS: unsupported placement amount handled cautiously; no invented salary")
