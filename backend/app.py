"""UniAI FastAPI gateway with durable MongoDB conversations when configured.

Conversation IDs are bearer-like tokens: clients must generate unpredictable
UUIDs and reuse the returned ID. MongoDB sessions are TTL-limited and leased
across workers. For a public multi-user service, add real authentication,
authorization and privacy controls before exposing session history endpoints.
"""

import asyncio
import logging
import os
import threading
import time
import uuid
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from Module4.main import ask_uniai
from Module4.conversation_state import ConversationState
from Module4.evidence import sources_from_records
from session_persistence import MongoSessionStore, SessionBusyError, SessionLeaseLostError


def _int_setting(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(minimum, min(value, maximum))


SESSION_TTL_SECONDS = _int_setting("UNIAI_SESSION_TTL_SECONDS", 6 * 3600, 60, 7 * 86400)
MAX_SESSIONS = _int_setting("UNIAI_MAX_SESSIONS", 500, 1, 10000)
# Existing MONGO_URI makes production sessions durable by default; local
# development can explicitly use UNIAI_SESSION_STORAGE=memory.
SESSION_STORAGE = os.getenv(
    "UNIAI_SESSION_STORAGE", "mongo" if os.getenv("MONGO_URI") else "memory",
).lower().strip()
SESSION_LEASE_SECONDS = _int_setting("UNIAI_SESSION_LEASE_SECONDS", 600, 120, 1800)
_shared_session_store = None


app = FastAPI(title="UniAI Backend - MAKAUT Academic Assistant")

extra_origins = [
    item.strip().rstrip("/")
    for item in os.getenv("UNIAI_CORS_ORIGINS", "").split(",")
    if item.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        *extra_origins,
    ],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+)(:\d+)?",
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    # Existing React frontend sends a crypto.randomUUID() value here.
    conversation_id: Optional[str] = Field(
        default=None, min_length=1, max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    # A retry must reuse the same ID so a timed-out response can be replayed
    # without regenerating a second answer or appending a duplicate turn.
    request_id: Optional[str] = Field(
        default=None, min_length=1, max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )


# All registry mutations are guarded by _registry_lock. Every conversation has
# its own lock to keep concurrent requests for that ID in conversational order.
session_store: Dict[str, ConversationState] = {}
_session_locks: Dict[str, threading.RLock] = {}
_session_last_seen: Dict[str, float] = {}
_session_in_flight: Dict[str, int] = {}
_registry_lock = threading.RLock()


def _cleanup_sessions(now: float) -> None:
    """Called with _registry_lock held; never evict a request in progress."""
    expired = [
        cid for cid, last_seen in _session_last_seen.items()
        if now - last_seen >= SESSION_TTL_SECONDS
        and _session_in_flight.get(cid, 0) == 0
    ]
    for cid in expired:
        _evict(cid)


def _evict(cid: str) -> None:
    """Called with _registry_lock held."""
    session_store.pop(cid, None)
    _session_locks.pop(cid, None)
    _session_last_seen.pop(cid, None)
    _session_in_flight.pop(cid, None)


def _acquire_session(requested_id: Optional[str]):
    """Reserve one conversation before obtaining its per-session lock."""
    cid = requested_id or uuid.uuid4().hex
    with _registry_lock:
        now = time.monotonic()
        _cleanup_sessions(now)
        if cid not in session_store:
            if len(session_store) >= MAX_SESSIONS:
                # Least-recently-used, but only if there is no in-flight request.
                idle = [
                    key for key in session_store
                    if _session_in_flight.get(key, 0) == 0
                ]
                if not idle:
                    raise HTTPException(
                        status_code=503, detail="All chat sessions are busy. Try again."
                    )
                victim = min(idle, key=lambda key: _session_last_seen[key])
                _evict(victim)
            session_store[cid] = ConversationState()
            _session_locks[cid] = threading.RLock()
            _session_in_flight[cid] = 0
        _session_last_seen[cid] = now
        _session_in_flight[cid] += 1
        return cid, session_store[cid], _session_locks[cid]


def _release_session(cid: str) -> None:
    with _registry_lock:
        _session_in_flight[cid] -= 1
        _session_last_seen[cid] = time.monotonic()


def _get_shared_session_store():
    """Lazy Mongo initialization; fail closed instead of losing chat context."""
    global _shared_session_store
    with _registry_lock:
        if _shared_session_store is None:
            from pymongo import MongoClient

            uri = os.getenv("MONGO_URI")
            if not uri:
                raise RuntimeError("MONGO_URI required for durable sessions")
            mongo = MongoClient(uri, serverSelectionTimeoutMS=8000)
            database = mongo["university_assistant"]
            _shared_session_store = MongoSessionStore(
                database["uniai_chat_sessions"],
                database["university_documents"],
                ttl_seconds=SESSION_TTL_SECONDS,
                lease_seconds=SESSION_LEASE_SECONDS,
            )
        return _shared_session_store


def _process_chat(request, cid, state):
    if request.request_id:
        replay = state.recent_requests.get(request.request_id)
        if replay is not None:
            # A repeated request ID must refer to exactly the same question,
            # never return a cached response from a different user request.
            if replay.get("question") != request.question:
                raise HTTPException(
                    status_code=409,
                    detail="Request ID was already used for a different question.",
                )
            return {**replay["response"], "conversation_id": cid}

    previous_turn = state.get_last_turn()
    answer = ask_uniai(request.question, state=state)
    current_turn = state.get_last_turn()
    records = (
        current_turn.get("records", [])
        if current_turn is not previous_turn and isinstance(current_turn, dict)
        else []
    )
    response = {
        "answer": answer,
        "sources": sources_from_records(records),
        "conversation_id": cid,
    }
    if request.request_id:
        state.recent_requests[request.request_id] = {
            "question": request.question,
            "response": dict(response),
        }
        # A small bounded cache prevents unbounded state growth.
        while len(state.recent_requests) > 15:
            del state.recent_requests[next(iter(state.recent_requests))]
    return response


@app.get("/health")
def health():
    with _registry_lock:
        _cleanup_sessions(time.monotonic())
        count = len(session_store)
    return {"status": "ok", "service": "UniAI Backend", "active_sessions": count}


@app.post("/api/chat")
def chat(request: ChatRequest):
    cid = request.conversation_id or uuid.uuid4().hex
    if SESSION_STORAGE == "mongo":
        try:
            with _get_shared_session_store().session(cid) as session_state:
                return _process_chat(request, cid, session_state)
        except SessionBusyError:
            raise HTTPException(
                status_code=409,
                detail="This conversation has another request in progress. Retry after it finishes.",
            )
        except SessionLeaseLostError:
            raise HTTPException(
                status_code=409, detail="Session changed during request; retry safely.",
            )
        except HTTPException:
            raise
        except Exception as exc:
            logging.exception("[UniAI API] Durable chat failed (%s)", type(exc).__name__)
            raise HTTPException(
                status_code=503,
                detail="Conversation storage or answer service is temporarily unavailable. Retry.",
            )
    if SESSION_STORAGE != "memory":
        raise HTTPException(status_code=503, detail="Invalid chat storage configuration")

    # Local/offline development keeps existing per-conversation lock behavior.
    cid, session_state, session_lock = _acquire_session(cid)
    try:
        with session_lock:
            return _process_chat(request, cid, session_state)
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("[UniAI API] Chat failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Unable to generate an answer.")
    finally:
        _release_session(cid)
