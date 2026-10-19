"""Offline Phase 3 regression checks (no live MongoDB, Pinecone or Ollama).

Run from backend/: python3 test_phase3.py
"""
import importlib.util
import sys
import types
from pathlib import Path
from datetime import datetime, timezone

# Import the real retrieval code without connecting to external databases.
pymongo = types.ModuleType("pymongo")
class DummyMongoClient:
    def __getitem__(self, key):
        return self
pymongo.MongoClient = lambda *a, **kw: DummyMongoClient()
pinecone = types.ModuleType("pinecone")
class DummyPinecone:
    def Index(self, name):
        return None
pinecone.Pinecone = lambda *a, **kw: DummyPinecone()
sys.modules.setdefault("pymongo", pymongo)
sys.modules.setdefault("pinecone", pinecone)

module_path = Path(__file__).resolve().parent / "retrieve.py"
spec = importlib.util.spec_from_file_location("uniai_phase3", module_path)
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)

first = {
    "notice_id": "first", "status": "processed",
    "title": "Notice on WBJEEB 2025 1st Counselling",
    "structured_data": {
        "title": "Document verification for WBJEEB-2025 allotted students",
        "issue_date": "29-08-2025", "target_audience": "WBJEEB-2025 (1st round)",
        "key_points": ["Report 3-7 September 2025, 2 p.m. to 4 p.m."],
    },
}
second = {
    "notice_id": "second", "status": "processed",
    "title": "WBJEEB 2nd Round Notice",
    "structured_data": {
        "title": "Document verification for WBJEEB-2025 allotted students",
        "issue_date": "08-09-2025", "target_audience": "WBJEEB-2025 (2nd round)",
        "key_points": ["Report 9-11 September 2025, 12 noon to 4 p.m."],
    },
}
jeca = {
    "notice_id": "jeca", "status": "processed",
    "title": "JECA Counselling Notice 2025-26",
    "structured_data": {
        "title": "JECA-2025 Counselling",
        "issue_date": "11-12-2025",
        "key_points": ["First round 17-21 Dec 2025; second round 23-26 Dec 2025", "WBJEEB website"],
    },
}
new = {
    "notice_id": "vacant", "status": "processed",
    "title": "In-House B. Tech Decentralized Admission Notice",
    "structured_data": {
        "title": "Vacant Seats for UG Courses in MAKAUT, WB - 2026-2027",
        "issue_date": "14-10-2026",
        "summary": "B.Tech vacant seats CSE, IT, Electronics VLSI and Industrial Engineering.",
        "key_points": ["Apply 14-27 Oct 2026", "Fee information available online"],
    },
}
jan = {
    "notice_id": "jan", "status": "processed",
    "title": "B.Tech Lateral Entry and MCA Decentralized Admission",
    "structured_data": {"title": "B.Tech and MCA", "issue_date": "21-01-2026"},
}
records = [first, second, jeca, new, jan]

class FakeCursor(list):
    def limit(self, n):
        return FakeCursor(self[:n])

class FakeCollection:
    def __init__(self):
        self.calls = []
    def find(self, query):
        self.calls.append(query)
        if "notice_id" in query:
            allowed = set(query["notice_id"]["$in"])
            return FakeCursor(rec for rec in records if rec["notice_id"] in allowed)
        return FakeCursor(records)

class FakeIndex:
    def __init__(self):
        self.calls = []
    def search_records(self, namespace, query):
        self.calls.append((namespace, query))
        ids = ["first", "second", "jeca", "jan", "vacant"]
        return {"result": {"hits": [{"_id": key} for key in ids]}}

collection = FakeCollection()
idx = FakeIndex()
r.notices_collection = collection
r.index = idx

q_second = "What are reporting dates for WBJEEB-2025 second-round document verification?"
chosen = r.retrieve_context(q_second, 5)
assert chosen[0]["notice_id"] == "second", [x["notice_id"] for x in chosen]
assert all(x["notice_id"] != "jeca" for x in chosen)
assert not any(x["notice_id"] == "first" for x in chosen)
assert len([q for q in collection.calls if "notice_id" in q]) == 1, "batch Mongo fetch must replace per-hit find_one"
print("PASS: correct second-round document wins, JECA excluded, one bulk Mongo read")

q_compare = "Compare first-round and second-round WBJEEB-2025 document verification requirements."
chosen = r.retrieve_context(q_compare, 5)
assert {x["notice_id"] for x in chosen} == {"first", "second"}, chosen
print("PASS: two WBJEEB rounds retained for comparison")

q_date = "Explain the MAKAUT vacant B.Tech seats notice dated 14 October 2026."
chosen = r.retrieve_context(q_date, 5)
assert [x["notice_id"] for x in chosen] == ["vacant"], chosen
print("PASS: exact issue-date notice selection excludes same-year lateral-entry notice")

assert r.is_pure_time_query("5 latest notices")
assert not r.is_pure_time_query("latest WBJEEB notices")
assert r.retrieve_context("5 latest notices", 2)[0]["notice_id"] == "vacant"
print("PASS: generic latest route remains chronological")

assert r._explicit_issue_date("What is the reporting deadline on 28 October 2026?") is None
assert r._explicit_issue_date("Notice dated 14 October 2026") == datetime(2026, 10, 14).date()
assert r._requested_rounds(q_compare) == {1, 2}
print("PASS: distinguish notice issue date from requested deadlines and both rounds")

now_local = datetime.now(r.INDIA_TZ).date()
today = dict(new, notice_id="today", structured_data={"issue_date": now_local.strftime("%d-%m-%Y")})
records.append(today)
chosen = r.retrieve_context("today's latest notices", 5)
assert {x["notice_id"] for x in chosen} == {"today"}, chosen
print("PASS: today notifications use Asia/Kolkata calendar day")

text = r.build_context_string([second], question=q_second)
assert "WBJEEB-2025" in text and "Official Source URL" in text
assert r.extract_relevant_snippets("", q_second) == []
print("PASS: Phase 2 context builder and snippet extractor signatures preserved")
print("ALL PHASE 3 OFFLINE TESTS PASSED")
