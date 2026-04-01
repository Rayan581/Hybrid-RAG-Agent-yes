# =============================================================================
# backend/src/admin/router.py
# Admin API endpoints — all protected by require_admin dependency.
# Only JWT tokens with "admin": true can access these routes.
# =============================================================================

import asyncio
import logging
import statistics
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.auth.security import require_admin
from src import db
from src.conversation.memory import list_active_sessions, get_or_create_session

logger = logging.getLogger(__name__)

admin_router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(require_admin)],
)

# ---------------------------------------------------------------------------
# Benchmark queries (mirrors benchmarks/runner.py)
# ---------------------------------------------------------------------------
BENCHMARK_QUERIES = [
    # General Domain (Shopping)
    {"query": "Show me Samsung phones under 150000 PKR",          "type": "general"},
    {"query": "What are the best laptops for students on Daraz?",  "type": "general"},
    {"query": "Compare the iPhone 15 and Samsung S24",            "type": "general"},
    {"query": "I need a gaming chair, budget 25000",              "type": "general"},
    {"query": "What's the return policy on electronics?",         "type": "general"},

    # Out-of-Domain (Should be rejected)
    {"query": "Who is the prime minister of Pakistan?",           "type": "ood"},
    {"query": "How do I treat a severe fever?",                   "type": "ood"},
    {"query": "Can you write a Python script for a web scraper?", "type": "ood"},
]

# Memory test is handled separately (stateful multi-turn setup required)
MEMORY_TEST_PRIME   = "I want to buy a Samsung Galaxy Tab S9 for college"
MEMORY_FILLER       = [
    "What are the best wireless earbuds under 5000?",
    "Tell me about gaming mice on Daraz",
    "Any good office chairs available?",
    "What keyboards do you recommend?",
]
MEMORY_RECALL_QUERY = "By the way, what was the item I told you I was interested in buying earlier?"


# =============================================================================
# LIVE SESSION MONITOR
# =============================================================================
@admin_router.get("/sessions")
async def admin_sessions():
    """Returns a summary of all active sessions with token estimates."""
    from src.conversation.compaction import estimate_tokens

    session_ids = list_active_sessions()
    results = []
    for sid in session_ids:
        session = get_or_create_session(sid)
        history = session.get("history", [])
        token_est = estimate_tokens(history)
        from src.config import N_CTX
        pct = token_est / N_CTX
        results.append({
            "session_id":    sid,
            "user_id":       session.get("user_id"),
            "turns":         session.get("turns", 0),
            "turn_count":    session.get("turn_count", 0),
            "token_estimate": token_est,
            "context_pct":   round(pct * 100, 1),
            "status":        session.get("status", "active"),
            "near_limit":    pct >= 0.78,   # yellow indicator threshold
        })
    return {"active_count": len(results), "sessions": results}


# =============================================================================
# MEMORY HEALTH — COMPACTION STATS
# =============================================================================
@admin_router.get("/compaction/stats")
async def compaction_stats(hours: int = 24):
    """Returns compaction event counts and token averages for the dashboard."""
    stats = await db.get_compaction_stats(hours=hours)
    return {"hours": hours, "stats": stats}


# =============================================================================
# BENCHMARK RUNNER (SSE streaming progress)
# =============================================================================
@admin_router.post("/benchmark/run")
async def run_benchmark(n_runs: int = 3):
    """
    Triggers the benchmark runner and streams results via SSE.
    Each line is a JSON object: {"query": ..., "avg_latency_ms": ..., "status": ...}
    """
    from src.engine.llm import llm_engine

    async def _stream():
        import json as _json
        import uuid as _uuid

        # ── General + OOD queries ───────────────────────────────────────────
        for entry in BENCHMARK_QUERIES:
            query     = entry["query"]
            test_type = entry["type"]

            latencies = []
            for _ in range(n_runs):
                session_id = str(_uuid.uuid4())
                t0 = time.perf_counter()
                try:
                    result  = await asyncio.wait_for(
                        llm_engine.generate(session_id=session_id, user_message=query),
                        timeout=60.0,
                    )
                    latency = (time.perf_counter() - t0) * 1000
                    latencies.append(latency)

                    passed = True
                    if test_type == "ood":
                        resp_lower = result["response"].lower()
                        passed = any(
                            kw in resp_lower
                            for kw in ["shopping assistant", "cannot provide", "medical", "unrelated",
                                       "only help", "only assist", "not able to", "outside"]
                        )

                    yield f"data: {_json.dumps({'query': query, 'latency_ms': round(latency, 1), 'status': 'ok', 'passed': passed, 'type': test_type, 'response_preview': result['response'][:80] + '...'})}\n\n"
                except Exception as e:
                    yield f"data: {_json.dumps({'query': query, 'status': 'error', 'error': str(e), 'type': test_type})}\n\n"


        # ── CRM / Cross-Session Recall test (Persistence verification) ─────
        for _ in range(n_runs):
            test_user_id = f"test-bench-{_uuid.uuid4().hex[:8]}"
            session_id_1 = str(_uuid.uuid4())
            session_id_2 = str(_uuid.uuid4())
            
            try:
                # Part 1: Registration session
                # We need to manually initialize the session with the user_id
                get_or_create_session(session_id_1, user_id=test_user_id)
                
                name = "Awwab" if _ % 2 == 0 else "Uwaid"
                pref = "HP laptops" if _ % 2 == 0 else "Gaming PC"
                
                prime_msg = f"My name is {name} and I am looking for a {pref}."
                await llm_engine.generate(session_id=session_id_1, user_message=prime_msg)

                # Part 2: Recall session (new session_id, same user_id)
                get_or_create_session(session_id_2, user_id=test_user_id)
                await refresh_crm_block(session_id_2)
                
                t0 = time.perf_counter()
                recall_query = "What is my name and what kind of product was I looking for previously?"
                result = await asyncio.wait_for(
                    llm_engine.generate(session_id=session_id_2, user_message=recall_query),
                    timeout=60.0,
                )
                latency = (time.perf_counter() - t0) * 1000
                
                resp_lower = result["response"].lower()
                passed = name.lower() in resp_lower and (pref.lower() in resp_lower or "laptop" in resp_lower or "gaming" in resp_lower)
                
                yield f"data: {_json.dumps({'query': recall_query, 'latency_ms': round(latency, 1), 'status': 'ok', 'passed': passed, 'type': 'crm', 'response_preview': result['response'][:80] + '...'})}\n\n"
            except Exception as e:
                yield f"data: {_json.dumps({'query': 'CRM Recall Test', 'status': 'error', 'error': str(e), 'type': 'crm'})}\n\n"

        yield f"data: {_json.dumps({'done': True})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


@admin_router.post("/benchmark/concurrency")
async def concurrency_test(n_users: int = 5):
    """
    Simulates multiple users hitting the LLM simultaneously.
    Streams results via SSE for live frontend feedback.
    """
    from src.engine.llm import llm_engine
    import uuid as _uuid
    import json as _json
    import statistics as _stats

    async def _stream():
        query   = "What is the best Samsung phone under 50000 PKR?"
        sessions = [str(_uuid.uuid4()) for _ in range(n_users)]

        t0      = time.perf_counter()
        
        # We wrap each task to capture its successful completion individually
        async def _run_one(idx, sid):
            st = time.perf_counter()
            try:
                r = await llm_engine.generate(sid, query)
                lat = (time.perf_counter() - st) * 1000
                return {
                    "user_index": idx + 1,
                    "session_id": sid[:8] + "…",
                    "latency_ms": round(lat, 1),
                    "status": "ok",
                    "response_preview": r.get("response", "")[:60] + "…",
                    "lat_raw": lat
                }
            except Exception as e:
                return {
                    "user_index": idx + 1,
                    "session_id": sid[:8] + "…",
                    "latency_ms": None,
                    "status": "error",
                    "response_preview": str(e),
                    "lat_raw": 0
                }

        tasks = [_run_one(i, sid) for i, sid in enumerate(sessions)]
        
        per_user = []
        # as_completed allows us to stream results as they finish
        for next_task in asyncio.as_completed(tasks):
            result = await next_task
            per_user.append(result)
            # Yield individual result
            yield f"data: {_json.dumps({'individual_result': result})}\n\n"

        total_time = (time.perf_counter() - t0) * 1000
        latencies = [r["lat_raw"] for r in per_user if r["status"] == "ok"]
        errors = sum(1 for r in per_user if r["status"] == "error")
        avg_lat = round(_stats.mean(latencies), 1) if latencies else 0
        p95_lat = round(sorted(latencies)[int(len(latencies) * 0.95)], 1) if len(latencies) > 1 else (latencies[0] if latencies else 0)

        # Final summary
        yield f"data: {_json.dumps({
            'done': True,
            'n_users':        n_users,
            'total_time_ms':  round(total_time, 1),
            'avg_latency_ms': avg_lat,
            'p95_latency_ms': p95_lat,
            'errors':         errors,
            'status':         'success' if errors == 0 else 'partial_failure',
            'per_user':       per_user,
        })}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


@admin_router.get("/benchmark/history")
async def benchmark_history(limit: int = 100):
    rows = await db.get_benchmark_history(limit=limit)
    return {"results": rows}


# =============================================================================
# USER / CRM TABLE
# =============================================================================
@admin_router.get("/users")
async def list_users(page: int = 1, page_size: int = 20):
    users = await db.list_users(page=page, page_size=page_size)
    return {"page": page, "page_size": page_size, "users": users}


@admin_router.get("/users/{user_id}/crm")
async def get_user_crm(user_id: str):
    profile = await db.get_crm_profile(user_id)
    if not profile:
        raise HTTPException(404, detail="CRM profile not found.")
    return profile


@admin_router.post("/users/{user_id}/unlock")
async def unlock_user(user_id: str):
    user = await db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(404, detail="User not found.")
    await db.unlock_user(user_id)
    return {"message": f"User {user_id} unlocked.", "user_id": user_id}
