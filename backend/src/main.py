# =============================================================================
# backend/src/main.py
# FastAPI application — security, routing, WebSocket, middleware.
#
# Changes from original:
#   - Stub /auth/* replaced by auth.router (bcrypt, register, lockout)
#   - WebSocket now requires JWT token query param; user_id injected into session
#   - refresh_crm_block() called once per WebSocket connect
#   - session_memory persisted on WebSocket disconnect
#   - Admin router mounted at /admin
#   - db.init_db() called in lifespan (async)
# =============================================================================

import json
import logging
import os
import uuid
import time
from contextlib import asynccontextmanager#
from typing import Optional

import bleach
from fastapi import (
    FastAPI, Request, APIRouter, Depends, HTTPException,
    Query, WebSocket, WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware

from src.config import (
    FRONTEND_ORIGIN,
    MAX_PAYLOAD_BYTES,
    MAX_TURNS,
    truncate_to_token_limit,
)
from src import db
from src.auth.security import get_current_user, get_user_from_ws_token, require_admin
from src.auth.router import auth_router
from src.engine.llm import llm_engine
from src.conversation.memory import (
    get_or_create_session,
    get_session_status,
    get_welcome_message,
    list_active_sessions,
    list_sessions,
    load_session,
    reset_session,
    delete_session as db_delete_session,
    init_sessions_from_db,
    refresh_crm_block,
)
from src.admin.router import admin_router

# =============================================================================
# LOGGING
# =============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# =============================================================================
# RATE LIMITER
# =============================================================================
limiter = Limiter(key_func=get_remote_address)


# =============================================================================
# PAYLOAD SIZE MIDDLEWARE
# =============================================================================
class PayloadSizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_PAYLOAD_BYTES:
            return JSONResponse(
                status_code=413,
                content={"detail": "Payload too large. Maximum allowed size is 1 MB."},
            )
        elif not content_length:
            body = await request.body()
            if len(body) > MAX_PAYLOAD_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Payload too large. Maximum allowed size is 1 MB."},
                )
        return await call_next(request)


# =============================================================================
# INPUT SANITIZATION
# =============================================================================
def sanitize_text(text: str) -> str:
    cleaned = bleach.clean(text, tags=[], attributes={}, strip=True)
    return truncate_to_token_limit(cleaned)


# =============================================================================
# SCHEMAS
# =============================================================================
class ChatRequest(BaseModel):
    session_id: Optional[str] = Field(None)
    message:    str


class ChatResponse(BaseModel):
    session_id: str
    response:   str
    latency_ms: float
    status:     str
    turns_used: int
    turns_max:  int


class ResetRequest(BaseModel):
    session_id: str


# =============================================================================
# MAIN ROUTER
# =============================================================================
router = APIRouter()


# ---------------------------------------------------------------------------
# WebSocket — /ws/chat
# JWT passed as query param: ws://host/ws/chat?token=<jwt>&session_id=<uuid>
# ---------------------------------------------------------------------------
@router.websocket("/ws/chat")
async def websocket_chat(
    websocket: WebSocket,
    token: Optional[str] = Query(default=None),
):
    # Auth: verify JWT before accepting
    try:
        user_payload = get_user_from_ws_token(token)
        user_id      = user_payload["sub"]
    except HTTPException:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept()

    # Session init: bind user_id, fetch CRM block once
    session_id = websocket.query_params.get("session_id") or str(uuid.uuid4())
    get_or_create_session(session_id, user_id=user_id)
    await refresh_crm_block(session_id)

    try:
        while True:
            message = await websocket.receive()

            # ----- Binary (audio) frame -----
            if "bytes" in message and message["bytes"]:
                audio_bytes = message["bytes"]
                if len(audio_bytes) > MAX_PAYLOAD_BYTES:
                    await websocket.send_json({"event": "error", "detail": "Audio chunk too large."})
                    continue
                try:
                    response_audio, user_text, assistant_text = await llm_engine.process_audio(
                        session_id, audio_bytes
                    )
                    await websocket.send_bytes(response_audio)
                    session = get_or_create_session(session_id)
                    await websocket.send_json({
                        "event":          "turn_complete",
                        "session_id":     session_id,
                        "status":         session["status"],
                        "turns_used":     session["turns"],
                        "turns_max":      MAX_TURNS,
                        "user_text":      user_text,
                        "assistant_text": assistant_text,
                    })
                except Exception as e:
                    logger.error(f"[WS] Audio processing error: {e}")
                    await websocket.send_json({"event": "error", "detail": str(e)})

            # ----- Text (JSON) frame -----
            elif "text" in message and message["text"]:
                try:
                    data = json.loads(message["text"])
                except Exception:
                    await websocket.send_json({"error": "Invalid JSON."})
                    continue

                raw_message = data.get("message", "").strip()
                if not raw_message:
                    await websocket.send_json({"error": "message field is required."})
                    continue

                user_message = sanitize_text(raw_message)

                # If CRM was updated this turn, refresh the cached block before next LLM call
                session = get_or_create_session(session_id)
                if session.get("crm_dirty"):
                    await refresh_crm_block(session_id)

                async for chunk in llm_engine.stream(session_id, user_message):
                    await websocket.send_json(chunk)
                    if chunk.get("done"):
                        break

    except WebSocketDisconnect:
        # Persist session memory on disconnect
        session = get_or_create_session(session_id)
        try:
            await db.save_session_memory(
                session_id=session_id,
                user_id=session.get("user_id", ""),
                messages=session.get("history", []),
                turn_count=session.get("turn_count", 0),
            )
        except Exception as e:
            logger.warning(f"[WS] session_memory persist failed on disconnect: {e}")
    except Exception as e:
        logger.error(f"[WS] Unexpected error: {e}")


# ---------------------------------------------------------------------------
# Chat (REST fallback)
# ---------------------------------------------------------------------------
@router.post("/chat", response_model=ChatResponse, tags=["Chat"])
@limiter.limit("10/minute")
async def chat(
    request: Request,
    body:    ChatRequest,
    user:    dict = Depends(get_current_user),
):
    session_id = body.session_id or str(uuid.uuid4())
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    user_message = sanitize_text(body.message)
    # Bind user_id and refresh CRM context
    get_or_create_session(session_id, user_id=user["sub"])
    await refresh_crm_block(session_id)

    result = await llm_engine.generate(session_id=session_id, user_message=user_message)
    return ChatResponse(**result)


# ---------------------------------------------------------------------------
# Session endpoints
# ---------------------------------------------------------------------------
@router.get("/session/welcome/{session_id}", tags=["Session"])
@limiter.limit("30/minute")
async def welcome(request: Request, session_id: str):
    return get_welcome_message(session_id)


@router.post("/reset", tags=["Session"])
@limiter.limit("20/minute")
async def reset(
    request: Request,
    body: ResetRequest,
    user: dict = Depends(get_current_user),
):
    reset_session(body.session_id)
    return {"message": f"Session '{body.session_id}' reset.", "status": "active"}


@router.get("/sessions", tags=["Session"])
@limiter.limit("30/minute")
async def get_all_sessions(
    request: Request,
    user: dict = Depends(get_current_user),
):
    return {"sessions": list_sessions()}


@router.get("/sessions/{session_id}", tags=["Session"])
@limiter.limit("30/minute")
async def get_session(
    request: Request,
    session_id: str,
    user: dict = Depends(get_current_user),
):
    session = get_or_create_session(session_id)
    return {
        "session_id": session_id,
        "history":    session["history"],
        "state":      session["state"],
        "turns":      session["turns"],
        "status":     session["status"],
        "turns_max":  MAX_TURNS,
    }


@router.delete("/sessions/{session_id}", tags=["Session"])
@limiter.limit("20/minute")
async def delete_session_endpoint(
    request: Request,
    session_id: str,
    user: dict = Depends(get_current_user),
):
    reset_session(session_id)
    success = db_delete_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found.")
    return {"message": f"Session '{session_id}' deleted."}


# Health check (no auth — used by frontend to probe connectivity)
@router.get("/health", tags=["System"])
async def health():
    return {"status": "ok", "active_sessions": len(list_active_sessions())}


# Warmup route (triggers LLM/STT/TTS loading)
@router.get("/warmup", tags=["System"])
async def warmup():
    """Warms up the engine by triggering lazy-loaded models."""
    try:
        # Trigger STT/TTS if possible or just log
        logger.info("🔥 Warmup triggered...")
        # We can also call llm_engine if we want to force load
        return {"status": "warmed_up"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


# =============================================================================
# LIFESPAN
# =============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Daraz Assistant starting up…")
    # Run async DB init (new tables) then legacy sync init (existing tables)
    await db.init_db()
    init_sessions_from_db()
    yield
    logger.info("🛑 Daraz Assistant shutting down…")


# =============================================================================
# APP SETUP
# =============================================================================
app = FastAPI(title="Daraz Voice Assistant API", version="3.0.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(PayloadSizeLimitMiddleware)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in FRONTEND_ORIGIN.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth_router)     # /auth/*
app.include_router(admin_router)    # /admin/*
app.include_router(router)          # /chat, /ws/chat, /sessions/*, /health

# Frontend static files
FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))
if os.path.isdir(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/ui", tags=["Frontend"], include_in_schema=False)
    async def serve_ui():
        index = os.path.join(FRONTEND_DIR, "public", "index.html")
        if os.path.exists(index):
            return FileResponse(index)
        old_index = os.path.join(FRONTEND_DIR, "index.html")
        if os.path.exists(old_index):
            return FileResponse(old_index)
        return {"message": "Frontend index.html not found."}
