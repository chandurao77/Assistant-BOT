# Assistant Bot — Copilot Instructions

## Project Overview
Assistant Bot — Assistant Bot. RAG-based AI assistant that answers questions from your own documents, running entirely on local models.

## Architecture
- **Backend**: FastAPI (Python 3.11) — RAG pipeline, multi-source ingestion, streaming chat, SSO/OIDC
- **Frontend**: React 19 + TypeScript + Vite — chat UI with source citations
- **Vector DB**: Qdrant v1.12.1 (container) — semantic search over all ingested content
- **LLM**: Ollama (local models) — answer generation
- **Embeddings**: `nomic-embed-text` via Ollama — 768-dimensional vectors
- **Persistence**: SQLite via aiosqlite (dev) / PostgreSQL via asyncpg (prod) — conversations, feedback, page index, page links, query analytics
- **Auth**: JWT + bcrypt + OIDC/SSO (Azure AD, Okta, Auth0) + RBAC (space-level access)
- **Observability**: structlog + ELK + OpenTelemetry tracing + Prometheus /metrics
- **Infra**: Podman Compose (dev) / Kubernetes with HPA (prod)

### Data Source Integration Patterns
- **Confluence**: Optional batch ingestion via REST API → Qdrant. Served from Qdrant at query time.
- **Jira**: Optional batch ingestion via REST API → Qdrant.
- **GitHub**: Optional batch ingestion via REST API → Qdrant.

## Key Conventions
- Backend: async FastAPI, Pydantic v2 models, structured logging (structlog)
- RAG: chunk size 512 tokens, overlap 64, top-k=3 retrieval, cosine similarity threshold 0.35
- Graph RAG: page hyperlinks stored in SQLite `page_links` table; one-hop expansion at query time
- Streaming: Server-Sent Events (SSE) via sse-starlette (events: token, sources, query_corrected, error, done)
- Anti-hallucination: LLM instructed to answer ONLY from retrieved context; refuses if no sources found
- Source citations: every answer includes page title, URL, space key, similarity score, and last-modified date
- Small-talk bypass: 530+ phrases across 17 categories short-circuit RAG in chat.py event_generator()
- Spell correction: corpus-based edit-distance correction in rag.py (_correct_question); builds vocabulary from ingested chunks, skips acronyms and technical terms
- Frontend: Tailwind CSS, no component library dependencies
- Error boundary: ErrorBoundary.tsx wraps App in main.tsx — catches React crashes with fallback UI
- Accessibility: ARIA labels on inputs/buttons, role="log" + aria-live="polite" on MessageList
- Embedding cache: _EmbedCache in embeddings.py — TTL 5 min, max 256 entries for query embeddings
- Exception handling: chat.py catches ConnectError, ReadTimeout, generic separately; services catch (httpx.HTTPError, OSError)
- Health endpoints: use singleton services via request.app.state.pipeline (no per-request instantiation)
- CI/CD: GitHub Actions (.github/workflows/ci.yml) — backend pytest, frontend lint+typecheck+test+build, container image builds + Trivy scan, GHCR push, K8s deploy
- Code quality: pyproject.toml configures black, isort, mypy; pytest-asyncio for async test support
- Containers: .dockerignore files in backend/ and frontend/ for smaller images
- Env config: `.env` file (gitignored), never hard-code secrets; `.env.example` must stay in sync
- SSO/OIDC: OIDCProvider in oidc.py handles discovery, auth URL, token exchange; auto-provisions users
- RBAC: require_space_access() dependency in dependencies.py enforces space-level access via JWT claims
- Async ingestion: ingest_worker.py runs as standalone container (podman compose --profile worker), Redis BLPOP queue
- Telemetry: setup_telemetry(app, settings) in telemetry.py — OTLP trace export + Prometheus /metrics endpoint (always on)
- Database migrations: Alembic in backend/alembic/ — initial schema migration for 6 tables

## File Structure
```
backend/app/
  config.py              — pydantic-settings env config (all tunable knobs)
  main.py                — FastAPI app, CORS, rate-limit middleware, lifespan
  api/
    routes/
      chat.py            — POST /api/chat/stream (SSE, small-talk bypass, specific error handling)
      ingest.py          — POST /api/ingest, /api/ingest/jira, /api/ingest/github, /api/ingest/local, GET /api/ingest/status
      health.py          — GET /api/health, /api/health/metrics, /api/health/spaces (singleton services)
      conversations.py   — GET/DELETE/PATCH /api/conversations
      feedback.py        — POST /api/feedback
      upload.py          — POST /api/upload, DELETE /api/upload/{id}
      auth.py            — POST /api/auth/register, /login, GET /sso/login, POST /sso/callback
    dependencies.py      — X-API-Key auth + RBAC require_space_access() factory
  services/
    rag.py               — RAG pipeline: embed → _retrieve() → _build_llm_context() → stream()
    llm.py               — Ollama streaming client (retry logic)
    embeddings.py        — Ollama /api/embed batch client (retry logic, TTL query cache)
    vector_store.py      — Qdrant wrapper: upsert, search, fetch_by_page_ids
    conversation_store.py — SQLite: persistent connection, conversations, messages, feedback, page_links, analytics
    pg_conversation_store.py — PostgreSQL alternative (horizontal scaling)
    auth.py              — User store (SQLite or PostgreSQL), JWT, SSO user provisioning
    oidc.py              — OIDC provider (discovery, auth URL, token exchange)
    ingest_worker.py     — Async Redis-queue ingestion worker (standalone container)
    semantic_cache.py    — Qdrant-backed semantic answer cache
    content_guardrail.py — PII/secret redaction with Luhn credit card validation (input + output sides)
    input_guardrail.py   — Prompt injection detection (6 regex patterns)
    confluence.py        — Confluence REST API client (Server + Cloud, bearer + basic auth)
    jira.py              — Jira REST API client (issue ingestion, ADF parsing)
    github_client.py     — GitHub API client (repo files, PRs)
    intent_router.py     — Multi-source intent classification (Jira/GitHub/Confluence)
    query_rewriter.py    — Conditional LLM query rewrite for vague questions (parallel dual-query)
    bm25.py              — Okapi BM25 in-memory inverted index for hybrid search keyword leg
    reranker.py          — LLM cross-encoder re-ranking
    entity_store.py      — Cognee-lite entity extraction + SQLite storage
    local_loader.py      — Load local Markdown/HTML files for ingestion
    file_parser.py       — Upload file parser (txt, md, pdf, docx)
    redis_cache.py       — Optional shared cache layer
    slack_bot.py         — Slack bot (HMAC-verified)
    teams_bot.py         — Teams bot (Azure AD JWT)
  telemetry.py           — OpenTelemetry tracing + Prometheus /metrics
  models/
    schemas.py           — Pydantic request/response models
    document.py          — DocumentChunk internal model
  utils/
    html_parser.py       — HTML → clean text + extract_confluence_links()
    text_splitter.py     — Chunk text with overlap

backend/
  pyproject.toml         — black, isort, mypy, pytest-asyncio config
  alembic/               — database migrations (initial schema for 6 tables)
  .dockerignore          — excludes .git, __pycache__, data/, *.db, .env

frontend/src/
  components/Chat/  — ChatContainer, MessageList, MessageItem, ChatInput, SelectionPopup, SourceCitations
  components/ErrorBoundary.tsx — React error boundary (wraps App)
  components/Sidebar/ConversationSidebar.tsx — Conversation list panel
  hooks/useChat.ts  — state management (reducer + localStorage) + file upload
  hooks/useConversations.ts — conversation list, rename, move-to-folder
  hooks/useFolders.ts — folder CRUD (localStorage-persisted)
  hooks/useTheme.ts — dark/light mode (localStorage + system preference)
  services/api.ts   — backend SSE client
  services/conversationsApi.ts — server-side conversation fetch
  types/index.ts    — shared TypeScript types

frontend/
  .dockerignore          — excludes node_modules, dist, tests

k8s/                     — Kubernetes manifests (namespace, backend+HPA, worker, infra, ingress+WAF, config)
.github/workflows/ci.yml — CI/CD pipeline (tests, lint, container build+scan, GHCR push, K8s deploy)
```
