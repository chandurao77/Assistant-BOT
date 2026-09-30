"""FastAPI application — entry point."""
from __future__ import annotations
import asyncio
import logging
import logging.handlers
import socket
import time
import uuid as _uuid
from collections import defaultdict
from pathlib import Path

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from contextlib import asynccontextmanager

from app.config import get_settings
from app.api.routes import chat, ingest, health, conversations, feedback, upload, auth, integrations
from app.telemetry import setup_telemetry, REQUEST_COUNT, REQUEST_LATENCY
from app.pii_scrubber import scrub_pii

# ── Structured logging setup ──────────────────────────────────────────────────
_settings = get_settings()

# Optional: ship JSON logs to Logstash via TCP (when ELK profile is active)
_logstash_handler = None
if _settings.elk_enabled:
    try:
        _logstash_handler = logging.handlers.SocketHandler("logstash", 5000)
        _logstash_handler.setLevel(logging.getLevelName(_settings.log_level))
    except Exception:
        _logstash_handler = None  # Logstash not reachable — no problem

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        scrub_pii,  # PII scrubbing — masks emails, IPs, MACs, secrets in INFO+ logs
        structlog.dev.ConsoleRenderer() if _settings.environment == "development"
        else structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        logging.getLevelName(_settings.log_level)
    ),
    logger_factory=structlog.PrintLoggerFactory(),
)

# Standard logging — add Logstash TCP handler alongside console
logging.basicConfig(level=_settings.log_level)
if _logstash_handler:
    logging.getLogger().addHandler(_logstash_handler)
logger = structlog.get_logger()


# ── Rate-limit middleware ──────────────────────────────────────────────────────
class _ChatRateLimitMiddleware:
    """Sliding-window rate limiter scoped to /api/chat/stream and /api/ingest.

    Uses authenticated user ID when available (from JWT), falls back to IP.
    """

    _RATE_LIMITED_PATHS = {
        "/api/chat/stream",
        "/api/ingest",
        "/api/ingest/local",
        "/api/auth/login",
        "/api/auth/register",
    }

    def __init__(self, app: FastAPI, max_rpm: int = 30) -> None:
        self.app = app
        self.max_rpm = max_rpm
        self._max_keys = 10_000  # Cap to prevent memory exhaustion from IP rotation attacks
        self._windows: dict[str, list[float]] = defaultdict(list)

    def _extract_rate_key(self, scope) -> str:
        """Use IP address as rate limit key. JWT identity is verified in the dependency layer."""
        ip = (scope.get("client") or ("unknown",))[0]
        return f"ip:{ip}"

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http" and scope.get("path") in self._RATE_LIMITED_PATHS:
            key = self._extract_rate_key(scope)
            now = time.monotonic()
            timestamps = self._windows[key]
            # Evict timestamps older than 60 seconds
            cutoff = now - 60.0
            self._windows[key] = [t for t in timestamps if t > cutoff]
            if len(self._windows[key]) >= self.max_rpm:
                response = JSONResponse(
                    status_code=429,
                    content={"detail": f"Rate limit exceeded. Max {self.max_rpm} requests per minute."},
                )
                await response(scope, receive, send)
                return
            self._windows[key].append(now)
            # Evict oldest keys if we exceed the cap to prevent memory exhaustion
            if len(self._windows) > self._max_keys:
                oldest_keys = sorted(
                    self._windows.keys(),
                    key=lambda k: self._windows[k][-1] if self._windows[k] else 0,
                )
                for old_key in oldest_keys[: len(self._windows) - self._max_keys]:
                    del self._windows[old_key]
        await self.app(scope, receive, send)


# ── Lifespan ──────────────────────────────────────────────────────────────────
async def _init_services(app: FastAPI, settings) -> list:
    """Initialise all singleton services and attach them to app.state. Returns background tasks."""
    from app.services.vector_store import VectorStore
    from app.services.rag import RAGPipeline, refresh_spell_dictionary
    from app.services.redis_cache import RedisCache

    # Redis shared cache (optional — enabled via REDIS_ENABLED=true)
    redis_cache = RedisCache(settings)
    await redis_cache.connect()
    app.state.redis_cache = redis_cache

    vs = VectorStore(settings)
    try:
        await vs.ensure_collection()
        titles = await vs.list_titles()
        if titles:
            refresh_spell_dictionary(titles)
    except Exception as exc:
        logger.warning("Could not ensure Qdrant collection on startup", error=str(exc))

    app.state.pipeline = RAGPipeline(settings, redis_cache=redis_cache)

    try:
        await app.state.pipeline.semantic_cache.ensure_collection()
    except Exception as exc:
        logger.warning("Could not ensure semantic cache collection — cache disabled until next restart", error=str(exc))
        app.state.pipeline.semantic_cache._enabled = False

    # Conversation store
    if settings.database_url:
        from app.services.pg_conversation_store import PgConversationStore
        app.state.conversation_store = await PgConversationStore.create(settings.database_url)
        logger.info("Using PostgreSQL conversation store")
    else:
        from app.services.conversation_store import ConversationStore
        app.state.conversation_store = await ConversationStore.create("/app/data/conversations.db")
        if settings.environment == "production":
            logger.warning(
                "Using SQLite in production — single-writer, no connection pooling. "
                "Set DATABASE_URL for PostgreSQL to enable horizontal scaling."
            )
        else:
            logger.info("Using SQLite conversation store (dev mode)")

    # Auth service
    from app.services.auth import AuthService
    auth_db_path = "/app/data/conversations.db"
    app.state.auth = await AuthService.create(settings, auth_db_path, database_url=settings.database_url)

    # Entity store
    from app.services.entity_store import EntityStore
    app.state.entity_store = await EntityStore.create(settings, auth_db_path)

    # Background tasks
    tasks: list = []
    if settings.conversation_max_age_days > 0:
        tasks.append(asyncio.create_task(
            _prune_task(app.state.conversation_store, settings.conversation_max_age_days)
        ))
    if settings.ingest_auto_interval_hours > 0:
        tasks.append(asyncio.create_task(
            _auto_ingest_task(settings, app.state.conversation_store)
        ))
    if settings.semantic_cache_enabled:
        tasks.append(asyncio.create_task(
            _cache_cleanup_task(app.state.pipeline.semantic_cache)
        ))
    return tasks


async def _shutdown_services(app: FastAPI, tasks: list) -> None:
    """Cancel background tasks and close all services gracefully."""
    logger.info("Shutting down Assistant Bot — draining in-flight requests...")
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    redis_cache = getattr(app.state, "redis_cache", None)
    if redis_cache and hasattr(redis_cache, "close"):
        await redis_cache.close()

    pipeline = getattr(app.state, "pipeline", None)
    if pipeline:
        for svc in (pipeline.llm, pipeline.embeddings, pipeline.reranker):
            if svc and hasattr(svc, "close"):
                try:
                    await svc.close()
                except Exception:
                    pass

    store = getattr(app.state, "conversation_store", None)
    if store and hasattr(store, "close") and callable(store.close):
        try:
            await store.close()
        except TypeError:
            pass  # MagicMock in tests
    logger.info("Assistant Bot shutdown complete")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # ── Security startup checks ─────────────────────────────────────────
    if settings.environment == "production" and settings.jwt_secret == "assistant-bot-dev-secret-change-me":
        raise RuntimeError(
            "FATAL: JWT_SECRET must be changed from the default before production deployment. "
            "Set JWT_SECRET or JWT_SECRET_FILE to a strong random value."
        )
    if settings.environment not in ("development",) and settings.jwt_secret == "assistant-bot-dev-secret-change-me":
        raise RuntimeError(
            "FATAL: JWT_SECRET must be changed from the default in non-development environments. "
            "Set JWT_SECRET or JWT_SECRET_FILE to a strong random value."
        )

    logger.info(
        "Starting Assistant Bot",
        env=settings.environment,
        llm_model=settings.ollama_llm_model,
        embed_model=settings.ollama_embed_model,
    )

    tasks = await _init_services(app, settings)

    yield

    await _shutdown_services(app, tasks)

# ── App factory ───────────────────────────────────────────────────────────────
def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description="Assistant Bot — RAG-powered AI assistant that answers from your own documents",
        lifespan=lifespan,
        openapi_url="/api/openapi.json" if settings.environment != "production" else None,
        docs_url="/api/docs" if settings.environment != "production" else None,
        redoc_url="/api/redoc" if settings.environment != "production" else None,
    )

    # CORS — allow the React frontend origin
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-API-Key", "X-Request-ID"],
    )

    # Per-IP rate limiter — applied only to /api/chat/stream and /api/ingest
    if settings.rate_limit_enabled:
        app.add_middleware(_ChatRateLimitMiddleware, max_rpm=settings.rate_limit_rpm)

    # OpenTelemetry tracing + Prometheus /metrics endpoint
    setup_telemetry(app, settings=settings)

    # Request body size limit — reject oversized payloads before processing (10 MB)
    _MAX_BODY_SIZE = 10 * 1024 * 1024  # 10 MB

    @app.middleware("http")
    async def limit_request_body(request: Request, call_next):
        # Check Content-Length header first (fast path for honest clients)
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > _MAX_BODY_SIZE:
            return JSONResponse(
                status_code=413,
                content={"detail": f"Request body too large. Maximum size is {_MAX_BODY_SIZE // (1024 * 1024)} MB."},
            )
        # Also guard against chunked transfer encoding (no Content-Length header)
        # by reading the body and checking actual size for non-GET/HEAD/OPTIONS
        if request.method in ("POST", "PUT", "PATCH"):
            body = await request.body()
            if len(body) > _MAX_BODY_SIZE:
                return JSONResponse(
                    status_code=413,
                    content={"detail": f"Request body too large. Maximum size is {_MAX_BODY_SIZE // (1024 * 1024)} MB."},
                )
        return await call_next(request)

    # Security headers + Correlation ID middleware
    @app.middleware("http")
    async def security_and_correlation_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(_uuid.uuid4()))
        structlog.contextvars.bind_contextvars(request_id=request_id)
        start = time.monotonic()
        response = await call_next(request)
        duration = time.monotonic() - start
        # Prometheus metrics
        endpoint = request.url.path
        REQUEST_COUNT.labels(request.method, endpoint, response.status_code).inc()
        REQUEST_LATENCY.labels(request.method, endpoint).observe(duration)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # Relaxed CSP for Swagger UI docs pages; strict for all other routes
        if request.url.path in ("/api/docs", "/api/redoc", "/api/openapi.json"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "img-src 'self' https://fastapi.tiangolo.com data:; "
                "frame-ancestors 'none'"
            )
        else:
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        structlog.contextvars.unbind_contextvars("request_id")
        return response

    # Routers
    app.include_router(auth.router, prefix="/api")
    app.include_router(health.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")
    app.include_router(ingest.router, prefix="/api")
    app.include_router(conversations.router, prefix="/api")
    app.include_router(feedback.router, prefix="/api")
    app.include_router(upload.router, prefix="/api")

    # Slack & Teams bot integrations (enabled via config)
    settings_ = get_settings()
    if settings_.slack_enabled or settings_.teams_enabled:
        app.include_router(integrations.router, prefix="/api")

    return app


# ── Background task helpers ───────────────────────────────────────────────────
async def _prune_task(store, max_age_days: int) -> None:
    """Daily background task to delete old conversations."""
    while True:
        await asyncio.sleep(24 * 3600)
        try:
            await store.prune_old_conversations(max_age_days)
        except Exception as exc:
            logger.warning("Conversation pruning failed", error=str(exc))


async def _cache_cleanup_task(semantic_cache) -> None:
    """Hourly background task to evict expired semantic cache entries."""
    while True:
        await asyncio.sleep(3600)
        try:
            await semantic_cache.cleanup_expired()
        except Exception as exc:
            logger.warning("Semantic cache cleanup failed", error=str(exc))


async def _auto_ingest_task(settings, store) -> None:
    """Periodic background task to re-ingest local docs."""
    from app.services.embeddings import EmbeddingService
    from app.services.vector_store import VectorStore
    from app.services.local_loader import load_local_docs
    from app.utils.html_parser import html_to_text
    from app.utils.text_splitter import split_text
    from app.models.document import DocumentChunk

    interval = settings.ingest_auto_interval_hours * 3600
    # First run: wait a full interval before starting
    await asyncio.sleep(interval)

    while True:
        logger.info("Auto-ingest: starting scheduled local ingestion")
        try:
            docs_dir = Path("/app/test_docs")
            if not docs_dir.exists():
                logger.warning("Auto-ingest: /app/test_docs not found, skipping")
            else:
                # Timeout auto-ingest after 30 minutes to prevent hangs
                await asyncio.wait_for(_do_auto_ingest(settings, store, docs_dir), timeout=1800)
        except asyncio.TimeoutError:
            logger.error("Auto-ingest: timed out after 30 minutes — aborting this run")
        except Exception as exc:
            logger.warning("Auto-ingest failed", error=str(exc))
        await asyncio.sleep(interval)


async def _do_auto_ingest(settings, store, docs_dir: Path) -> None:
    """Run the actual auto-ingestion logic (called with timeout wrapper)."""
    from app.services.embeddings import EmbeddingService
    from app.services.vector_store import VectorStore
    from app.services.local_loader import load_local_docs
    from app.utils.html_parser import html_to_text
    from app.utils.text_splitter import split_text
    from app.models.document import DocumentChunk

    embed_service = EmbeddingService(settings)
    vector_store = VectorStore(settings)
    try:
        await vector_store.ensure_collection()
        pages = load_local_docs(docs_dir)
        existing = await store.get_page_versions([p.page_id for p in pages])
        ingested = 0
        for page in pages:
            new_lm = page.last_modified.isoformat()
            if existing.get(page.page_id) == new_lm:
                continue
            plain = html_to_text(page.body_html) if "<" in page.body_html else page.body_html
            if not plain.strip():
                continue
            raw_chunks = split_text(plain, chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
            doc_chunks = [
                DocumentChunk(
                    chunk_id=f"{page.page_id}_{c.index}", page_id=page.page_id,
                    title=page.title, space_key=page.space_key, space_name=page.space_name,
                    url=page.url, text=c.text, chunk_index=c.index,
                    total_chunks=len(raw_chunks), last_modified=page.last_modified,
                )
                for c in raw_chunks
            ]
            vectors = await embed_service.embed_batch([c.text for c in doc_chunks])
            await vector_store.upsert_chunks(doc_chunks, vectors)
            await store.upsert_page_index(page.page_id, new_lm, len(doc_chunks))
            ingested += 1
        logger.info("Auto-ingest: completed — %d pages updated", ingested)
    finally:
        if hasattr(embed_service, 'close'):
            await embed_service.close()
        if hasattr(vector_store, 'close'):
            await vector_store.close()


app = create_app()
