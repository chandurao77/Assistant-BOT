"""Health check, metrics, and spaces endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import get_optional_user, require_admin
from app.models.schemas import HealthResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthResponse)
async def health_check(request: Request):
    """Return health status of all components."""
    pipeline = request.app.state.pipeline

    qdrant_ok = await pipeline.vector_store.health()
    ollama_ok = await pipeline.llm.health()

    # Try a dummy embedding to verify embedding model is loaded
    embed_ok = True
    try:
        await pipeline.embeddings.embed("health check")
    except Exception:
        embed_ok = False

    # Database connectivity check
    db_ok = True
    db_type = "sqlite"
    try:
        store = request.app.state.conversation_store
        if hasattr(store, "_pool"):
            db_type = "postgresql"
        await store.get_analytics()
    except Exception:
        db_ok = False

    # Ingest status
    from app.api.routes.ingest import _ingest_status
    ingest_running = _ingest_status.get("running", False)

    components = {
        "qdrant": "ok" if qdrant_ok else "down",
        "ollama_llm": "ok" if ollama_ok else "down",
        "ollama_embeddings": "ok" if embed_ok else "down",
        "database": "ok" if db_ok else "down",
    }

    # Redis health (optional — only shown when enabled)
    redis_cache = getattr(request.app.state, "redis_cache", None)
    if redis_cache and redis_cache.available:
        redis_ok = await redis_cache.health()
        components["redis"] = "ok" if redis_ok else "down"

    all_ok = all(v == "ok" for v in components.values())
    status = "ok" if all_ok else ("degraded" if qdrant_ok else "down")

    return HealthResponse(
        status=status,
        components=components,
        database_type=db_type,
        ingest_running=ingest_running,
    )


@router.get("/metrics", tags=["metrics"])
async def get_metrics(request: Request):
    """Return aggregate query analytics: total queries, no-answer rate, etc."""
    store = request.app.state.conversation_store
    return await store.get_analytics()


@router.get("/spaces", tags=["spaces"])
async def list_spaces(request: Request, user: dict | None = Depends(get_optional_user)):
    """Return the distinct Confluence spaces currently indexed in Qdrant."""
    pipeline = request.app.state.pipeline
    all_spaces = await pipeline.vector_store.list_spaces()
    allowed = user.get("allowed_spaces", []) if user else []
    if not allowed:
        return all_spaces
    return [s for s in all_spaces if s.get("key") in allowed or s.get("space_key") in allowed]


@router.get("/admin-stats", tags=["admin"])
async def admin_stats(request: Request, _admin: dict = Depends(require_admin)):
    """Return comprehensive system stats for the admin dashboard."""
    pipeline = request.app.state.pipeline
    store = request.app.state.conversation_store
    auth_service = getattr(request.app.state, "auth", None)

    # System health
    qdrant_ok = await pipeline.vector_store.health()
    ollama_ok = await pipeline.llm.health()
    embed_ok = True
    try:
        await pipeline.embeddings.embed("health check")
    except Exception:
        embed_ok = False
    db_ok = True
    try:
        await store.get_analytics()
    except Exception:
        db_ok = False

    components = {
        "qdrant": "ok" if qdrant_ok else "down",
        "ollama_llm": "ok" if ollama_ok else "down",
        "ollama_embeddings": "ok" if embed_ok else "down",
        "database": "ok" if db_ok else "down",
    }
    redis_cache = getattr(request.app.state, "redis_cache", None)
    if redis_cache and redis_cache.available:
        redis_ok = await redis_cache.health()
        components["redis"] = "ok" if redis_ok else "down"

    # Vector store stats
    try:
        total_chunks = await pipeline.vector_store.count()
    except Exception:
        total_chunks = 0

    # Indexed spaces
    try:
        spaces = await pipeline.vector_store.list_spaces()
    except Exception:
        spaces = []

    # Ingestion status
    from app.api.routes.ingest import _ingest_status
    ingest = dict(_ingest_status)

    # User count
    user_count = 0
    users_list = []
    if auth_service:
        try:
            if hasattr(auth_service, '_pg_pool') and auth_service._pg_pool:
                async with auth_service._pg_pool.acquire() as conn:
                    row = await conn.fetchrow("SELECT COUNT(*) as cnt FROM users")
                    user_count = row["cnt"]
                    rows = await conn.fetch("SELECT id, name, email, role, created_at FROM users ORDER BY created_at DESC LIMIT 50")
                    users_list = [dict(r) for r in rows]
            else:
                import aiosqlite
                async with aiosqlite.connect(auth_service._db_path) as db:
                    async with db.execute("SELECT COUNT(*) FROM users") as cur:
                        user_count = (await cur.fetchone())[0]
                    async with db.execute("SELECT id, name, email, role, created_at FROM users ORDER BY created_at DESC LIMIT 50") as cur:
                        rows = await cur.fetchall()
                        users_list = [{"id": r[0], "name": r[1], "email": r[2], "role": r[3], "created_at": r[4]} for r in rows]
        except Exception:
            pass

    # Database type
    db_type = "postgresql" if hasattr(store, "_pool") else "sqlite"

    # Extended analytics (9 features)
    try:
        extended = await store.get_extended_analytics()
    except Exception:
        extended = {}

    # Cache hit rate (feature #8)
    from app.services.semantic_cache import SemanticCache
    cache_stats = SemanticCache.get_stats()

    return {
        "system": {
            "components": components,
            "database_type": db_type,
            "all_healthy": all(v == "ok" for v in components.values()),
        },
        "vector_store": {
            "total_chunks": total_chunks,
            "indexed_spaces": spaces,
            "space_count": len(spaces),
        },
        "ingestion": ingest,
        "users": {
            "total": user_count,
            "list": users_list,
        },
        "analytics": extended,
        "cache": cache_stats,
    }
