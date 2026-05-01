# =============================================================================
# backend/src/engine/llm.py
# Voice-to-Voice orchestration engine.
#
# Changes from original:
#   - Added generate_non_streaming() for internal summarization calls
#   - process_audio / generate / stream now follow the 7-step turn order:
#       1. auto_compact_if_needed
#       2. RAG retrieval (ephemeral — not stored in history)
#       3. build prompt + stream/generate LLM response
#       4. append user + assistant messages to history
#       5. apply_micro_compact (clear consumed tool results)
#       6. maybe_extract_to_crm (background, non-blocking)
#   - refresh_crm_block called at session init (once per WebSocket connect)
# =============================================================================

import io
import json
import logging
import os
import tempfile
import time
import asyncio
from typing import Optional, AsyncGenerator
from concurrent.futures import ThreadPoolExecutor

import wave
import moonshine_onnx as moonshine
from piper import PiperVoice
from llama_cpp import Llama

from src.config import (
    MAX_TURNS, MAX_TOKENS, N_CTX, N_THREADS, N_BATCH,
    TEMPERATURE, TOP_P, REPEAT_PENALTY,
    RAG_MAX_CONTEXT_TOKENS,
)
from src.conversation.memory import (
    build_inference_payload,
    add_message_to_chat,
    extract_and_strip_state,
    increment_turn,
    is_session_maxed,
    get_session_status,
    set_session_status,
    is_conversation_resolved,
    get_or_create_session,
    apply_micro_compact,
    refresh_crm_block,
    flush_session_to_db,
)
from src.conversation.compaction import (
    auto_compact_if_needed,
    maybe_extract_to_crm,
    estimate_tokens,
)
from src.retrieval.search import retriever


logger = logging.getLogger(__name__)

# Thread pool for blocking model inference (increased from 1 to 10 for better concurrency)
_executor = ThreadPoolExecutor(max_workers=10)

# =============================================================================
# STT MODEL
# =============================================================================
_MOONSHINE_MODEL = "moonshine/base"
logger.info(f"[engine] Moonshine STT model: {_MOONSHINE_MODEL}")

# =============================================================================
# TTS MODEL
# =============================================================================
_piper_model_path = os.getenv("PIPER_MODEL", "/models/en_US-lessac-medium.onnx")
try:
    _tts_model = PiperVoice.load(_piper_model_path)
    logger.info(f"✅ [engine] Piper TTS loaded: {_piper_model_path}")
except Exception as _e:
    logger.error(f"❌ [engine] Piper TTS load failed: {_e}")
    _tts_model = None

# =============================================================================
# LLM MODEL
# =============================================================================
_model_path = os.getenv("MODEL_PATH", "/models/qwen2.5-3b-instruct-q4_k_m.gguf")
logger.info(f"[engine] Loading LLM model from: {_model_path}")
try:
    _llm = Llama(
        model_path=_model_path,
        n_ctx=N_CTX,
        n_threads=N_THREADS,
        n_batch=N_BATCH,
        n_gpu_layers=0,
        verbose=True,
    )
    logger.info("✅ [engine] LLM model loaded successfully.")
except Exception as e:
    logger.error(f"❌ [engine] LLM load failed: {e}")
    _llm = None


# =============================================================================
# STAGE 1 — SPEECH-TO-TEXT
# =============================================================================
async def transcribe_audio(audio_bytes: bytes, session_id: str) -> str:
    logger.info(f"[engine] STT called | session={session_id} | {len(audio_bytes)} bytes")

    def _run_stt() -> str:
        suffix = ".wav" if audio_bytes[:4] == b"RIFF" else ".webm"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            raw_path = tmp.name

        wav_path = None
        try:
            import subprocess
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_tmp:
                wav_path = wav_tmp.name
            subprocess.run(
                ["ffmpeg", "-y", "-i", raw_path, "-ac", "1", "-ar", "16000", wav_path],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            transcripts = moonshine.transcribe(wav_path, _MOONSHINE_MODEL)
            return " ".join(t.strip() for t in transcripts).strip()
        finally:
            for p in (raw_path, wav_path):
                if p and os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _run_stt)


# =============================================================================
# STAGE 3 — TEXT-TO-SPEECH
# =============================================================================
async def synthesize_speech(text: str, session_id: str) -> bytes:
    if _tts_model is None:
        raise RuntimeError("Piper TTS model not loaded.")

    def _run_tts() -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(_tts_model.config.sample_rate)
            _tts_model.synthesize(text, wav_file)
        return buf.getvalue()

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _run_tts)


# =============================================================================
# INTERNAL LLM HELPERS
# =============================================================================
from src.config import build_chatml_prompt


def _run_llm_sync(prompt: str, max_tokens: int) -> str:
    """Blocking call — must run in executor."""
    if _llm is None:
        raise RuntimeError("LLM not loaded.")
    return "".join(
        chunk["choices"][0]["text"]
        for chunk in _llm(
            prompt,
            max_tokens=max_tokens,
            stop=["<|im_end|>", "<|endoftext|>", "<|im_start|>"],
            echo=False,
            temperature=TEMPERATURE,
            top_p=TOP_P,
            repeat_penalty=REPEAT_PENALTY,
            stream=True,
        )
    )


async def _llm_generate_non_streaming(messages: list[dict], max_tokens: int = 400) -> str:
    """
    Non-streaming LLM call for internal use (summarization, CRM extraction).
    Never yields tokens to the user.
    """
    if _llm is None:
        raise RuntimeError("LLM not loaded.")
    prompt = build_chatml_prompt(messages)
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _run_llm_sync, prompt, max_tokens)


async def _generate_text(session_id: str, user_text: str) -> str:
    """Stage 2: RAG retrieval + LLM generation (full response, non-streaming)."""
    if _llm is None:
        raise RuntimeError("LLM not loaded.")

    # RAG — ephemeral, injected into system prompt only (not stored in history)
    rag_context = retriever.get_relevant_context(user_text)
    if estimate_tokens([{"content": rag_context}]) > RAG_MAX_CONTEXT_TOKENS:
        rag_context = rag_context[: RAG_MAX_CONTEXT_TOKENS * 4]

    messages = build_inference_payload(session_id, user_text, rag_context=rag_context)
    prompt   = build_chatml_prompt(messages)

    loop = asyncio.get_event_loop()
    raw_response = await loop.run_in_executor(_executor, _run_llm_sync, prompt, MAX_TOKENS)
    return extract_and_strip_state(session_id, raw_response)


# =============================================================================
# ORCHESTRATION LAYER
# =============================================================================
class VoiceEngine:

    def _check_lifecycle_guards(self, session_id: str) -> Optional[str]:
        if _llm is None:
            return "I'm temporarily unavailable. Please try again later."
        if get_session_status(session_id) == "ended":
            return "This session has ended. Please start a new chat."
        if is_session_maxed(session_id):
            set_session_status(session_id, "ended")
            farewell = "We've reached the end of our session. Thank you for shopping with Daraz Assistant!"
            add_message_to_chat(session_id, "assistant", farewell)
            return farewell
        return None

    async def _post_turn_hooks(self, session_id: str) -> None:
        """
        Background memory work — runs AFTER user response is sent.
        All operations are fire-and-forget; errors are logged, never raised.
        """
        loop = asyncio.get_event_loop()
        # Step 5: Micro-compact (fast, in-memory — still sync but cheap)
        apply_micro_compact(session_id)
        # Flush to SQLite in background thread (non-blocking)
        loop.run_in_executor(_executor, flush_session_to_db, session_id)
        # Step 6: Background CRM extraction (already fire-and-forget)
        session = get_or_create_session(session_id)
        await maybe_extract_to_crm(session, _llm_generate_non_streaming)

    # -------------------------------------------------------------------------
    # AUDIO PATH (voice chat)
    # -------------------------------------------------------------------------
    async def process_audio(self, session_id: str, audio_bytes: bytes) -> tuple[bytes, str, str]:
        guard_text = self._check_lifecycle_guards(session_id)
        if guard_text:
            return await synthesize_speech(guard_text, session_id), "", guard_text

        # Transcribe first — no blocking compaction before STT
        user_text = await transcribe_audio(audio_bytes, session_id)
        if not user_text.strip():
            silence_reply = "I didn't catch that — could you try again?"
            return await synthesize_speech(silence_reply, session_id), "", silence_reply

        # Generate LLM response
        assistant_text = await _generate_text(session_id, user_text)

        # Fast Redis-only updates
        add_message_to_chat(session_id, "user",      user_text)
        add_message_to_chat(session_id, "assistant", assistant_text)
        increment_turn(session_id)

        if get_session_status(session_id) != "ended" and is_conversation_resolved(session_id):
            set_session_status(session_id, "closing")

        # Synthesize audio and return immediately
        audio_response = await synthesize_speech(assistant_text, session_id)

        # Schedule all memory work AFTER audio is returned
        session = get_or_create_session(session_id)
        asyncio.create_task(self._background_memory_work(session_id, session))

        return audio_response, user_text, assistant_text

    # -------------------------------------------------------------------------
    # TEXT PATH (REST /chat endpoint)
    # -------------------------------------------------------------------------
    async def generate(self, session_id: str, user_message: str) -> dict:
        guard_text = self._check_lifecycle_guards(session_id)
        if guard_text:
            session = get_or_create_session(session_id)
            return {
                "response":   guard_text,
                "latency_ms": 0.0,
                "session_id": session_id,
                "status":     session.get("status", "active"),
                "turns_used": session.get("turns", 0),
                "turns_max":  MAX_TURNS,
            }

        start = time.perf_counter()

        # Generate response FIRST — compaction runs in background AFTER
        assistant_text = await _generate_text(session_id, user_message)

        # Fast in-memory updates (Redis only)
        add_message_to_chat(session_id, "user",      user_message)
        add_message_to_chat(session_id, "assistant", assistant_text)
        increment_turn(session_id)

        if get_session_status(session_id) != "ended" and is_conversation_resolved(session_id):
            set_session_status(session_id, "closing")

        session = get_or_create_session(session_id)
        result = {
            "response":   assistant_text,
            "latency_ms": round((time.perf_counter() - start) * 1000, 2),
            "session_id": session_id,
            "status":     session["status"],
            "turns_used": session["turns"],
            "turns_max":  MAX_TURNS,
        }

        # Schedule background memory work AFTER response is ready
        asyncio.create_task(self._background_memory_work(session_id, session))

        return result

    async def _background_memory_work(self, session_id: str, session: dict) -> None:
        """All memory work after a turn: compaction check, post-hooks. Non-blocking."""
        try:
            await auto_compact_if_needed(
                session, _llm_generate_non_streaming, context_window=N_CTX, session_id=session_id
            )
            await self._post_turn_hooks(session_id)
        except Exception as e:
            logger.warning(f"[engine] Background memory work failed for {session_id}: {e}")

    # -------------------------------------------------------------------------
    # STREAMING TEXT PATH (WebSocket)
    # -------------------------------------------------------------------------
    async def stream(self, session_id: str, user_message: str) -> AsyncGenerator[dict, None]:
        guard_text = self._check_lifecycle_guards(session_id)
        if guard_text:
            yield {"token": guard_text, "done": True}
            return

        if _llm is None:
            yield {"token": "LLM not loaded.", "done": True, "error": "LLM initialization failed."}
            return

        start = time.perf_counter()

        # RAG (ephemeral) — runs immediately, no compaction blocking
        rag_context = retriever.get_relevant_context(user_message)
        if estimate_tokens([{"content": rag_context}]) > RAG_MAX_CONTEXT_TOKENS:
            rag_context = rag_context[: RAG_MAX_CONTEXT_TOKENS * 4]

        # Build prompt from current session state
        messages = build_inference_payload(session_id, user_message, rag_context=rag_context)
        prompt   = build_chatml_prompt(messages)

        loop = asyncio.get_event_loop()
        token_queue: asyncio.Queue = asyncio.Queue()

        def _worker():
            try:
                for chunk in _llm(
                    prompt,
                    max_tokens=MAX_TOKENS,
                    stop=["<|im_end|>", "<|endoftext|>", "<|im_start|>"],
                    echo=False,
                    temperature=TEMPERATURE,
                    top_p=TOP_P,
                    repeat_penalty=REPEAT_PENALTY,
                    stream=True,
                ):
                    loop.call_soon_threadsafe(token_queue.put_nowait, chunk)
            except Exception as e:
                loop.call_soon_threadsafe(token_queue.put_nowait, e)
            finally:
                loop.call_soon_threadsafe(token_queue.put_nowait, None)

        loop.run_in_executor(_executor, _worker)

        full_text    = ""
        yield_buffer = ""
        hide_remaining = False

        while True:
            item = await token_queue.get()
            if item is None:
                break
            if isinstance(item, Exception):
                yield {"token": "", "done": True, "error": str(item)}
                return

            token = item["choices"][0]["text"]
            full_text += token

            if hide_remaining:
                continue

            yield_buffer += token
            if "<STATE>" in yield_buffer:
                hide_remaining = True
                valid_text, _ = yield_buffer.split("<STATE>", 1)
                if valid_text:
                    yield {"token": valid_text, "done": False}
                yield_buffer = ""
                continue

            match_len = 0
            for i in range(1, len("<STATE>") + 1):
                if yield_buffer.endswith("<STATE>"[:i]):
                    match_len = i

            if match_len > 0:
                safe_to_yield = yield_buffer[:-match_len]
                yield_buffer  = yield_buffer[-match_len:]
            else:
                safe_to_yield = yield_buffer
                yield_buffer  = ""

            if safe_to_yield:
                yield {"token": safe_to_yield, "done": False}

        if yield_buffer and not hide_remaining:
            yield {"token": yield_buffer, "done": False}

        # Persist to Redis immediately (fast — user gets done signal)
        clean_response = extract_and_strip_state(session_id, full_text)
        add_message_to_chat(session_id, "user",      user_message)
        add_message_to_chat(session_id, "assistant", clean_response.strip())
        increment_turn(session_id)

        if get_session_status(session_id) != "ended" and is_conversation_resolved(session_id):
            set_session_status(session_id, "closing")

        session = get_or_create_session(session_id)
        yield {
            "token":      "",
            "done":       True,
            "latency_ms": round((time.perf_counter() - start) * 1000, 2),
            "session_id": session_id,
            "status":     session["status"],
            "turns_used": session["turns"],
            "turns_max":  MAX_TURNS,
        }

        # Schedule ALL memory work AFTER done signal is sent to user
        asyncio.create_task(self._background_memory_work(session_id, session))


llm_engine = VoiceEngine()
