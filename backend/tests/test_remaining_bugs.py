"""Offline regression tests for final UniAI bug fixes #9-#12.

PYTHONPATH=backend python -m unittest discover -s backend/tests -p 'test_remaining_bugs.py' -v
"""
import ast
import json
import copy
import os
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from Module4.conversation_state import ConversationState
from session_persistence import (
    MongoSessionStore, SessionBusyError, snapshot_state, restore_state,
)


class FakeCursor(list):
    def sort(self, *args):
        return self

    def limit(self, amount):
        return FakeCursor(self[:amount])


class FakeNotices:
    def __init__(self, records):
        self.records = list(records)

    def find(self, query):
        ids = query.get("notice_id", {}).get("$in", [])
        return FakeCursor([r for r in self.records
                           if r.get("notice_id") in ids and r.get("status") == "processed"])


class FakeSessions:
    def __init__(self):
        self.sessions = {}
        self.indices = []

    def create_index(self, *args, **kwargs):
        self.indices.append((args, kwargs))

    def find_one_and_update(self, query, update, upsert=False, return_document=None):
        cid = query["_id"]
        now = datetime.now(timezone.utc)
        doc = self.sessions.get(cid)
        if doc and doc.get("lease_until", now) > now:
            raise FakeDuplicateKeyError("busy session")
        if doc is None:
            doc = {"_id": cid, **copy.deepcopy(update["$setOnInsert"])}
            self.sessions[cid] = doc
        doc.update(copy.deepcopy(update["$set"]))
        return copy.deepcopy(doc)

    def update_one(self, query, update):
        doc = self.sessions.get(query["_id"])
        matched = bool(doc and doc.get("lease_token") == query.get("lease_token"))
        if matched:
            doc.update(copy.deepcopy(update.get("$set") or {}))
            for key in (update.get("$unset") or {}):
                doc.pop(key, None)
        return types.SimpleNamespace(matched_count=int(matched))


class FakeDuplicateKeyError(Exception):
    pass


class ScopedPymongo:
    def __enter__(self):
        self.old = sys.modules.get("pymongo")
        self.old_errors = sys.modules.get("pymongo.errors")
        pymongo = types.ModuleType("pymongo")
        pymongo.ReturnDocument = types.SimpleNamespace(AFTER=1)
        errors = types.ModuleType("pymongo.errors")
        errors.DuplicateKeyError = FakeDuplicateKeyError
        pymongo.errors = errors
        sys.modules["pymongo"] = pymongo
        sys.modules["pymongo.errors"] = errors
        return self

    def __exit__(self, *exc):
        for name, old in (("pymongo", self.old), ("pymongo.errors", self.old_errors)):
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old


def record(nid):
    return {
        "notice_id": nid, "status": "processed",
        "title": f"Notice {nid}", "raw_text": "SENSITIVE RAW PDF OCR " * 100,
        "structured_data": {"title": f"Notice {nid}"},
    }


class DurableStateTests(unittest.TestCase):
    def setUp(self):
        self.notice = record("a")
        self.docs = FakeNotices([self.notice])
        self.sessions = FakeSessions()
        self.store = MongoSessionStore(
            self.sessions, self.docs, ttl_seconds=3600, lease_seconds=600
        )

    def test_snapshot_excludes_entire_pdf_text(self):
        state = ConversationState()
        state.append_turn("What does this notice say?", "Details", records=[self.notice],
                          active_notice=self.notice)
        snap = snapshot_state(state)
        self.assertNotIn("SENSITIVE RAW PDF OCR", str(snap))
        self.assertEqual(snap["active_notice_id"], "a")
        self.assertEqual(snap["last_notice_ids"], ["a"])

    def test_rehydrated_active_notice_survives_new_worker(self):
        with ScopedPymongo():
            with self.store.session("session-uuid-001") as s:
                s.append_turn("Show the notice", "Here is the notice",
                              records=[self.notice], active_notice=self.notice)
                s.session_memory["user_name"] = "Student"
            # A new store instance represents a different Render worker.
            other_worker = MongoSessionStore(
                self.sessions, self.docs, ttl_seconds=3600, lease_seconds=600
            )
            with other_worker.session("session-uuid-001") as restored:
                self.assertEqual(restored.get_active_notice_id(), "a")
                self.assertEqual(restored.get_last_notice_records()[0]["notice_id"], "a")
                self.assertEqual(restored.get_user_name(), "Student")
                self.assertEqual(restored.get_last_turn()["query"], "Show the notice")

    def test_restoring_deleted_notice_does_not_leak_stale_content(self):
        state = ConversationState()
        state.append_turn("Show", "Found", records=[self.notice],
                          active_notice=self.notice)
        self.notice["status"] = "new"
        restored = restore_state(snapshot_state(state), self.docs)
        self.assertIsNone(restored.get_active_notice())
        self.assertEqual(restored.get_last_notice_records(), [])

    def test_same_session_has_cross_worker_exclusive_lease(self):
        with ScopedPymongo():
            with self.store.session("session-uuid-002"):
                another_worker = MongoSessionStore(
                    self.sessions, self.docs, ttl_seconds=3600, lease_seconds=600
                )
                with self.assertRaises(SessionBusyError):
                    with another_worker.session("session-uuid-002"):
                        pass
            with another_worker.session("session-uuid-002"):
                pass

    def test_expired_session_does_not_restore_previous_user_name(self):
        with ScopedPymongo():
            with self.store.session("session-uuid-003") as s:
                s.session_memory["user_name"] = "Alice"
            self.sessions.sessions["session-uuid-003"]["expires_at"] = (
                datetime.now(timezone.utc) - timedelta(seconds=1)
            )
            with self.store.session("session-uuid-003") as new:
                self.assertIsNone(new.get_user_name())

    def test_recent_request_cache_survives_restart(self):
        with ScopedPymongo():
            with self.store.session("session-uuid-004") as state:
                state.recent_requests["req-1"] = {
                    "question": "What is the fee?",
                    "response": {"answer": "Not found", "sources": []},
                }
            with self.store.session("session-uuid-004") as restored:
                self.assertEqual(restored.recent_requests["req-1"]["response"]["answer"],
                                 "Not found")

    def test_snapshot_caps_history(self):
        state = ConversationState(max_turns_stored=5)
        for i in range(15):
            state.append_turn(f"q{i}", f"a{i}", records=[])
        self.assertLessEqual(len(snapshot_state(state)["chat_history"]), 5)

    def test_ttl_index_exists(self):
        self.assertEqual(self.sessions.indices[0][0], ("expires_at",))


def load_isolated(path, function_names, dependencies):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    nodes = [node for node in tree.body
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
             and node.name in function_names]
    module = ast.Module(body=nodes, type_ignores=[])
    namespace = dict(dependencies)
    exec(compile(module, str(path), "exec"), namespace)
    return namespace


class ReplayIdempotencyTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "app.py"
        class HTTPExceptionForTest(Exception):
            def __init__(self, status_code, detail):
                super().__init__(detail)
                self.status_code = status_code
        self.http_error = HTTPExceptionForTest
        self.calls = []
        def answer(question, state):
            self.calls.append(question)
            state.append_turn(question, f"Answer for {question}", records=[])
            return f"Answer for {question}"
        self.module = load_isolated(path, {"_process_chat"}, {
            "ask_uniai": answer,
            "sources_from_records": lambda records: [],
            "HTTPException": HTTPExceptionForTest,
        })
        self.state = ConversationState()

    def test_retry_same_request_returns_cached_answer_without_new_turn(self):
        request = types.SimpleNamespace(question="What is the fee?", request_id="req-1")
        first = self.module["_process_chat"](request, "chat-1", self.state)
        second = self.module["_process_chat"](request, "chat-1", self.state)
        self.assertEqual(first, second)
        self.assertEqual(self.calls, ["What is the fee?"])
        self.assertEqual(len(self.state.chat_history), 1)

    def test_reused_request_id_for_different_question_returns_conflict(self):
        request = types.SimpleNamespace(question="What is the fee?", request_id="req-1")
        self.module["_process_chat"](request, "chat-1", self.state)
        with self.assertRaises(self.http_error) as error:
            self.module["_process_chat"](
                types.SimpleNamespace(question="Other question", request_id="req-1"),
                "chat-1", self.state,
            )
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(len(self.calls), 1)

    def test_replay_response_persists_through_snapshot_restore(self):
        request = types.SimpleNamespace(question="Deadline?", request_id="req-2")
        first = self.module["_process_chat"](request, "chat-1", self.state)
        snapshot = snapshot_state(self.state)
        restored = restore_state(snapshot, FakeNotices([]))
        self.assertEqual(self.module["_process_chat"](request, "chat-1", restored), first)
        self.assertEqual(self.calls, ["Deadline?"])


class PdfRevisionTests(unittest.TestCase):
    def test_recheck_includes_review_pending_and_processed(self):
        path = Path(__file__).resolve().parents[1] / "Module1" / "scrapper.py"
        old = record("rev1")
        old.update({"_id": 1, "url": "https://makautwb.ac.in/doc.pdf",
                    "pdf_sha256": "old", "status": "review_required"})
        class Collection:
            def __init__(self):
                self.rows = [old]
                self.query = None
                self.updated = []

            def find(self, query):
                self.query = query
                return FakeCursor(self.rows)

            def update_one(self, query, update):
                self.updated.append((query, update))
                return types.SimpleNamespace(modified_count=1)
        col = Collection()
        env = load_isolated(path, {"recheck_existing_pdf_versions"}, {
            "notices_collection": col,
            "_pdf_digest": lambda url: "new",
            "datetime": datetime,
            "timezone": timezone,
        })
        result = env["recheck_existing_pdf_versions"](limit=2)
        self.assertIn("review_required", col.query["status"]["$in"])
        self.assertEqual(result["changed"], 1)
        conditions, update = col.updated[0]
        self.assertEqual(conditions["status"], "review_required")
        self.assertEqual(update["$set"]["status"], "new")
        self.assertFalse(update["$set"]["pinecone_indexed"])
        self.assertEqual(update["$set"]["processing_attempts"], 0)

    def test_recheck_unchanged_updates_only_tracking_time(self):
        path = Path(__file__).resolve().parents[1] / "Module1" / "scrapper.py"
        row = record("unchanged")
        row.update({"_id": 1, "url": "https://makautwb.ac.in/doc.pdf",
                    "pdf_sha256": "same"})
        class Collection:
            def find(self, query):
                return FakeCursor([row])

            def update_one(self, query, update):
                self.update = update
                return types.SimpleNamespace(modified_count=1)
        col = Collection()
        env = load_isolated(path, {"recheck_existing_pdf_versions"}, {
            "notices_collection": col, "_pdf_digest": lambda url: "same",
            "datetime": datetime, "timezone": timezone,
        })
        report = env["recheck_existing_pdf_versions"](limit=3)
        self.assertEqual(report["changed"], 0)
        self.assertIn("last_content_checked_at", col.update["$set"])
        self.assertNotIn("status", col.update["$set"])


class SyncThroughputTests(unittest.TestCase):
    def test_github_workflow_enables_bounded_catchup(self):
        path = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "notice_sync.yml"
        text = path.read_text()
        self.assertIn('SYNC_RECHECK_EXISTING: "3"', text)
        self.assertIn('SYNC_PROCESS_LIMIT: "3"', text)
        self.assertIn('SYNC_INDEX_LIMIT: "10"', text)

    def test_scheduler_passes_limits_to_processing_and_indexer(self):
        path = Path(__file__).resolve().parents[1] / "scheduler" / "sync_notices.py"
        env = load_isolated(path, {"_limit", "run_sync"}, {"os": os, "json": __import__("json")})
        calls = []
        with patch.dict(os.environ, {
            "SYNC_PROCESS_LIMIT": "3",
            "SYNC_INDEX_LIMIT": "10",
            "SYNC_RECHECK_EXISTING": "3",
        }):
            result = env["run_sync"](
                scrape_fn=lambda: {"new": 5},
                recheck_fn=lambda limit: calls.append(("recheck", limit)) or {"checked": limit},
                process_fn=lambda limit: calls.append(("process", limit)) or {"failed": 0},
                index_fn=lambda limit: calls.append(("index", limit)) or (2, 0),
            )
        self.assertEqual(calls, [("recheck", 3), ("process", 3), ("index", 10)])
        self.assertEqual(result["indexed"], 2)


class EvaluationFixtureTests(unittest.TestCase):
    def test_exactly_50_distinct_scenarios_across_nine_topics(self):
        path = Path(__file__).resolve().parents[1] / "evaluation" / "questions_50.json"
        questions = json.loads(path.read_text(encoding="utf-8"))["questions"]
        self.assertEqual(len(questions), 50)
        self.assertEqual(len({x["id"] for x in questions}), 50)
        topics = {x["category"] for x in questions}
        self.assertEqual(len(topics), 9)
        self.assertTrue(all(x["question"] and x["expected_behavior"] for x in questions))

    def test_multi_turn_followup_set_reuses_same_conversation(self):
        path = Path(__file__).resolve().parents[1] / "evaluation" / "questions_50.json"
        questions = json.loads(path.read_text(encoding="utf-8"))["questions"]
        followups = [x for x in questions if x["category"] == "followups"]
        self.assertEqual(len(followups), 6)
        self.assertEqual(len({x["conversation"] for x in followups}), 1)


if __name__ == "__main__":
    unittest.main()
