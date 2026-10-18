from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, Dict
import asyncio

from Module4.main import ask_uniai
from Module4.conversation_state import ConversationState
from Module4.evidence import sources_from_records

app = FastAPI(title="UniAI Backend - MAKAUT Academic Assistant")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: Optional[str] = None


# Multi-session state store (isolated per conversation tab)
session_store: Dict[str, ConversationState] = {}


def get_session_state(conversation_id: Optional[str]) -> ConversationState:
    cid = conversation_id or "default"
    if cid not in session_store:
        session_store[cid] = ConversationState()
    return session_store[cid]


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "UniAI Backend",
        "active_sessions": len(session_store)
    }


@app.post("/api/chat")
def chat(request: ChatRequest):
    try:
        session_state = get_session_state(request.conversation_id)
        previous_turn = session_state.get_last_turn()

        # Execute conversational RAG with session isolation
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
        }

    except asyncio.CancelledError:
        print("[UniAI] Request was cancelled by client or server shutdown.")
        raise
    except Exception as exc:
        print(f"UniAI API error: {exc}")
        raise HTTPException(
            status_code=500,
            detail="Unable to generate an answer."
        )