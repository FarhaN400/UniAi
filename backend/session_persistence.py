"""Durable, leased MongoDB conversation sessions for UniAI.

A session ID acts as a bearer secret: clients must use unpredictable UUIDs.
No PDF/OCR text is duplicated into sessions. We persist only notice_id refs,
bounded chat text, and recent request IDs for idempotent HTTP retries.

A MongoDB lease serializes requests for the same session across Render workers.
If a worker dies, the lease expires; do NOT fall back to a fresh local session
on MongoDB connection failures, as that would silently lose context.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import uuid

from Module4.conversation_state import ConversationState


class SessionBusyError(RuntimeError):
    """Another worker is already handling this conversation."""


class SessionLeaseLostError(RuntimeError):
    """A newer worker took over this timed-out lease."""


def _record_ids(records):
    return [
        str(record["notice_id"])
        for record in (records or [])
        if isinstance(record, dict) and record.get("notice_id")
    ][:25]


def snapshot_state(state):
    """Serialize bounded state without copying complete PDF/OCR records."""
    history = []
    for turn in (state.chat_history or [])[-state.max_turns_stored:]:
        if isinstance(turn, dict):
            history.append({
                "query": str(turn.get("query") or "")[:2000],
                "response": str(turn.get("response") or "")[:8000],
                "record_ids": _record_ids(turn.get("records")),
            })
    recent = dict(getattr(state, "recent_requests", {}) or {})
    return {
        "version": 1,
        "history_window": state.history_window,
        "max_turns_stored": state.max_turns_stored,
        "chat_history": history,
        "last_notice_ids": _record_ids(state.last_notice_records),
        "last_answer_ids": _record_ids(state.last_answer_records),
        "active_notice_id": state.active_notice_id,
        "session_memory": {
            "user_name": str(state.session_memory.get("user_name") or "")[:120]
        } if state.session_memory.get("user_name") else {},
        "recent_requests": {
            key: response for key, response in list(recent.items())[-15:]
            if isinstance(key, str) and isinstance(response, dict)
        },
    }


def restore_state(snapshot, notices_collection):
    """Restore active/numbered notice context from authoritative Mongo docs."""
    if not isinstance(snapshot, dict) or snapshot.get("version") != 1:
        return ConversationState()
    state = ConversationState(
        history_window=snapshot.get("history_window", 5),
        max_turns_stored=snapshot.get("max_turns_stored", 25),
    )
    ids = set(snapshot.get("last_notice_ids") or [])
    ids.update(snapshot.get("last_answer_ids") or [])
    if snapshot.get("active_notice_id"):
        ids.add(snapshot["active_notice_id"])
    for turn in snapshot.get("chat_history") or []:
        if isinstance(turn, dict):
            ids.update(turn.get("record_ids") or [])

    by_id = {}
    if ids:
        for record in notices_collection.find({
            "notice_id": {"$in": list(ids)},
            "status": "processed",
        }):
            if record.get("notice_id"):
                by_id[str(record["notice_id"])] = record

    def resolve(values):
        return [by_id[key] for key in (values or []) if key in by_id]

    state.chat_history = [
        {
            "query": str(turn.get("query") or ""),
            "response": str(turn.get("response") or ""),
            "records": resolve(turn.get("record_ids")),
        }
        for turn in (snapshot.get("chat_history") or [])
        if isinstance(turn, dict)
    ][-state.max_turns_stored:]
    state.set_last_results(resolve(snapshot.get("last_notice_ids")))
    state.set_last_answer_records(resolve(snapshot.get("last_answer_ids")))
    active = by_id.get(str(snapshot.get("active_notice_id") or ""))
    state.set_active_notice(active)
    memory = snapshot.get("session_memory") or {}
    if isinstance(memory, dict) and memory.get("user_name"):
        state.session_memory["user_name"] = str(memory["user_name"])[:120]
    recent = snapshot.get("recent_requests") or {}
    state.recent_requests = dict(recent) if isinstance(recent, dict) else {}
    return state


class MongoSessionStore:
    def __init__(self, collection, notices_collection, *,
                 ttl_seconds=21600, lease_seconds=600):
        self.collection = collection
        self.notices_collection = notices_collection
        self.ttl_seconds = int(ttl_seconds)
        self.lease_seconds = int(lease_seconds)
        if self.ttl_seconds < 60 or self.lease_seconds < 60:
            raise ValueError("Session TTL and lease must be at least one minute")
        # Background TTL cleanup; expiration is also enforced on read.
        self.collection.create_index("expires_at", expireAfterSeconds=0)

    @contextmanager
    def session(self, conversation_id):
        from pymongo import ReturnDocument
        from pymongo.errors import DuplicateKeyError

        token = uuid.uuid4().hex
        now = datetime.now(timezone.utc)
        conditions = {
            "_id": conversation_id,
            "$or": [
                {"lease_until": {"$exists": False}},
                {"lease_until": {"$lte": now}},
            ],
        }
        update = {
            "$set": {
                "lease_token": token,
                "lease_until": now + timedelta(seconds=self.lease_seconds),
            },
            "$setOnInsert": {
                "created_at": now,
                "expires_at": now + timedelta(seconds=self.ttl_seconds),
                "state": {},
            },
        }
        try:
            doc = self.collection.find_one_and_update(
                conditions, update, upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError as exc:
            raise SessionBusyError("A request is already running for this chat.") from exc
        if doc is None:
            raise SessionBusyError("A request is already running for this chat.")
        try:
            if doc.get("expires_at") and doc["expires_at"].replace(
                tzinfo=doc["expires_at"].tzinfo or timezone.utc
            ) <= now:
                saved = {}
            else:
                saved = doc.get("state") or {}
            state = restore_state(saved, self.notices_collection)
            yield state
            result = self.collection.update_one(
                {"_id": conversation_id, "lease_token": token},
                {
                    "$set": {
                        "state": snapshot_state(state),
                        "updated_at": datetime.now(timezone.utc),
                        "expires_at": datetime.now(timezone.utc)
                        + timedelta(seconds=self.ttl_seconds),
                    },
                    "$unset": {"lease_token": "", "lease_until": ""},
                },
            )
            if result.matched_count != 1:
                raise SessionLeaseLostError(
                    "The session lease expired during inference; retry this chat."
                )
        finally:
            # Only this lease owner may clear the lock; never release another
            # worker's lease after a timed-out request.
            self.collection.update_one(
                {"_id": conversation_id, "lease_token": token},
                {"$unset": {"lease_token": "", "lease_until": ""}},
            )
