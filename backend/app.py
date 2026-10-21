"""UniAI FastAPI gateway with process-local, isolated conversation sessions.

Conversation IDs are bearer-like values. Use an unpredictable client UUID or let
this API generate one, and always reuse the returned conversation_id on follow-ups.
For persistent sessions across Render restarts/multiple workers, use a shared
session store (e.g., MongoDB) plus an authentication/authorization design.
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


def _int_setting(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(minimum, min(value, maximum))


SESSION_TTL_SECONDS = _int_setting("UNIAI_SESSION_TTL_SECONDS", 6 * 3600, 60, 7 * 86400)
MAX_SESSIONS = _int_setting("UNIAI_MAX_SESSIONS", 500, 1, 10000)

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


@app.get("/health")
def health():
    with _registry_lock:
        _cleanup_sessions(time.monotonic())
        count = len(session_store)
    return {"status": "ok", "service": "UniAI Backend", "active_sessions": count}


@app.post("/api/chat")
def chat(request: ChatRequest):
    cid, session_state, session_lock = _acquire_session(request.conversation_id)
    try:
        with session_lock:
            previous_turn = session_state.get_last_turn()
            answer = ask_uniai(request.question, state=session_state)
            current_turn = session_state.get_last_turn()
            records = (
                current_turn.get("records", [])
                if current_turn is not previous_turn and isinstance(current_turn, dict)
                else []
            )
            sources = sources_from_records(records)
            return {
                "answer": answer,
                "sources": sources,
                "conversation_id": cid,
            }
    except asyncio.CancelledError:
        raise
    except HTTPException:
        raise
    except Exception as exc:
        # Don't expose internal MongoDB/Pinecone/API credentials in HTTP errors.
        logging.exception("[UniAI API] Chat failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Unable to generate an answer.")
    finally:
        _release_session(cid)
