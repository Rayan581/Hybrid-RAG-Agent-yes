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
    "Show me Samsung phones under 150000 PKR",
    "What are the best laptops for students on Daraz?",
    "Compare the iPhone 15 and Samsung S24",
    "I need a gaming chair, budget 25000",
    "What's the return policy on electronics?",
    
    # Out-of-Domain (Should be rejected)
    "OOD: Who is the prime minister of Pakistan?",
    "OOD: How do I treat a severe fever?",
    "OOD: Can you write a Python script for a web scraper?",
    
    # Memory / Context (Will be handled in a sequence by the runner)
    "MEM: What was the item I was interested in purchasing?",
]


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
        for query in BENCHMARK_QUERIES:
            test_type = "general"
            if query.startswith("OOD:"): test_type = "ood"
            elif query.startswith("MEM:"): test_type = "memory"
            
            clean_query = query.replace("OOD: ", "").replace("MEM: ", "")
            
            for _ in range(n_runs):
                import uuid as _uuid
                session_id = str(_uuid.uuid4())
                
                # Setup context for memory test
                if test_type == "memory":
                    await llm_engine.generate(session_id=session_id, user_message="I want to buy an iPhone 15 Pro Max")
                    for i in range(2):
                        await llm_engine.generate(session_id=session_id, user_message=f"Tell me about some accessories for that {i}")

                t0 = time.perf_counter()
                try:
                    result = await asyncio.wait_for(
                        llm_engine.generate(session_id=session_id, user_message=clean_query),
                        timeout=60.0,
                    )
                    latency = (time.perf_counter() - t0) * 1000
                    
                    passed = True
                    if test_type == "ood":
                        passed = any(kw in result["response"].lower() for kw in ["shopping assistant", "cannot provide", "medical", "unrelated"])
                    elif test_type == "memory":
                        passed = "iphone 15" in result["response"].lower()
                    
                    row = {
                        "query": query,
                        "latency_ms": round(latency, 1),
                        "status": "ok",
                        "passed": passed,
                        "type": test_type,
                        "response_preview": result["response"][:50] + "..."
                    }
                    yield f"data: {_json.dumps(row)}\n\n"
                except Exception as e:
                    yield f"data: {_json.dumps({'query': query, 'status': 'error', 'error': str(e)})}\n\n"

        yield f"data: {_json.dumps({'done': True})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


@admin_router.post("/benchmark/concurrency")
async def concurrency_test(n_users: int = 5):
    """
    Simulates multiple users hitting the LLM simultaneously.
    Measures total time and per-user average latency.
    """
    from src.engine.llm import llm_engine
    import uuid as _uuid
    
    query = "What is the best Samsung phone?"
    sessions = [str(_uuid.uuid4()) for _ in range(n_users)]
    
    t0 = time.perf_counter()
    tasks = [llm_engine.generate(sid, query) for sid in sessions]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    total_time = (time.perf_counter() - t0) * 1000
    
    latencies = [r["latency_ms"] for r in results if isinstance(r, dict)]
    errors = sum(1 for r in results if not isinstance(r, dict))
    
    return {
        "n_users": n_users,
        "total_time_ms": round(total_time, 1),
        "avg_latency_ms": round(sum(latencies)/len(latencies), 1) if latencies else 0,
        "errors": errors,
        "status": "success" if errors == 0 else "partial_failure"
    }


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
