# Assistant Bot — Agent Instructions & Safe Command Auto-Approvals

This file configures Copilot CLI and other AI coding agents for this project.

## Project Overview
Assistant Bot — Assistant Bot. RAG-based AI assistant for Confluence docs. Stack: FastAPI + React/Vite + Qdrant + Ollama, all running in Podman Compose.

## Auto-Approve: Safe Commands

The following commands are **safe to run automatically** without asking for confirmation.
They are non-destructive, read-only or additive, and will not modify production data or secrets.

### Podman / Infrastructure
```
podman compose ps
podman compose logs
podman compose logs --tail=50
podman compose up -d
podman compose up -d --build backend
podman compose up -d --build frontend
podman compose up -d --build
podman compose stop
podman compose restart backend
podman compose restart frontend
podman compose exec backend sh -c "..."
podman compose exec frontend sh -c "..."
.\run.ps1 -Status
.\run.ps1 -Logs
./run.sh --status
./run.sh --logs
```

### Backend Tests
```
podman compose exec backend sh -c "cd /app && python -m pytest tests/ -v"
podman compose exec backend sh -c "cd /app && python -m pytest tests/ -v --tb=short"
podman compose exec backend sh -c "cd /app && python -m pytest tests/ -q"
python -m pytest tests/ -v
python -m pytest tests/ -v --tb=short
```

### Frontend Tests & Build
```
npm test
npm test -- --run
npm run build
npm run lint
npm ci
```

### Health / Smoke Checks
```
Invoke-RestMethod -Uri http://localhost:8000/api/health
Invoke-RestMethod -Uri http://localhost:8000/api/health/metrics
Invoke-RestMethod -Uri http://localhost:8000/api/health/spaces
curl http://localhost:8000/api/health
```

### File Inspection (Read-only)
```
Get-Content <file>
cat <file>
type <file>
Get-ChildItem
ls
dir
```

### Git (Read-only)
```
git status
git log --oneline
git diff
git diff --staged
git branch
```

## Require Confirmation Before Running

The following **must always require explicit user confirmation**:

- `podman compose down` — stops all containers
- `podman compose down -v` — destroys volumes (data loss)
- `git push` — pushes to remote
- `git commit` — creates a commit
- Any command writing to `.env` — contains secrets
- Any `DELETE` or `DROP` SQL commands against production DB
- `podman compose exec backend sh -c "... DELETE ..."` — destructive DB ops
- Ingestion with `full_refresh=true` — drops and rebuilds the vector index

## Key Conventions

- **Never hardcode secrets** — all secrets in `.env` (gitignored) or `secrets/` directory
- **Backend** changes require `podman compose up -d --build backend` to apply
- **Frontend** changes require `podman compose up -d --build frontend` to apply
- Run `podman compose exec backend sh -c "cd /app && python -m pytest tests/ -v"` after any backend change
- Run `cd frontend && npm test -- --run` after any frontend change
- The `.env.example` must be updated whenever new config vars are added to `config.py`

## File Structure Quick Reference
```
backend/app/
  config.py         — pydantic-settings (add env vars here, supports _FILE secrets)
  main.py           — FastAPI app, middleware, _init_services/_shutdown_services, background tasks
  migrate_sqlite_to_pg.py — SQLite → PostgreSQL data migration script
  api/routes/       — chat.py, ingest.py, health.py, conversations.py, feedback.py (+ reason dropdown + auto-reingest), upload.py,
                      auth.py (register, login, SSO/OIDC), integrations.py
  api/dependencies.py — shared FastAPI deps (auth, RBAC space access check)
  services/         — rag.py (+ _retrieve/_build_llm_context), llm.py (Ollama), embeddings.py (+ TTL cache), vector_store.py,
                      confluence.py (Confluence REST API client — Server + Cloud),
                      conversation_store.py (SQLite, persistent connection), pg_conversation_store.py (PostgreSQL),
                      semantic_cache.py, content_guardrail.py, input_guardrail.py, file_parser.py,
                      auth.py (user store SQLite/PostgreSQL, JWT, SSO provisioning), oidc.py (OIDC provider),
                      ingest_worker.py (async Redis-queue worker),
                      jira.py (Jira REST client + issue_to_chunks),
                      github_client.py (GitHub API client + file/PR ingestion),
                      intent_router.py (multi-source query routing),
                      query_rewriter.py (conditional LLM query rewrite for vague questions),
                      reranker.py (LLM cross-encoder re-ranking),
                      bm25.py (Okapi BM25 in-memory inverted index for hybrid search),
                      entity_store.py (Cognee-lite entity extraction),
                      slack_bot.py, teams_bot.py
  models/schemas.py — Pydantic request/response models
  telemetry.py      — OpenTelemetry tracing + Prometheus /metrics (Settings-based config)

backend/
  pyproject.toml    — black, isort, mypy, pytest-asyncio config
  alembic/          — database migrations (001 initial schema, 002 feedback reason columns)
  .dockerignore     — excludes .git, __pycache__, data/, *.db, .env

frontend/src/
  components/Chat/  — ChatContainer, MessageList, MessageItem (+ copy button, feedback reason picker), ChatInput, SelectionPopup, SourceCitations
  components/ErrorBoundary.tsx — React error boundary (wraps App)
  components/Layout/Header.tsx — Header + dark/light mode toggle
  components/Sidebar/ConversationSidebar.tsx — Search, folders, rename, delete, move-to-folder
  hooks/useChat.ts  — state management (reducer + localStorage) + file upload
  hooks/useConversations.ts — conversation list, rename, move-to-folder
  hooks/useFolders.ts — folder CRUD (localStorage-persisted)
  hooks/useTheme.ts  — dark/light mode (localStorage + system preference)
  services/api.ts   — backend SSE client
  services/conversationsApi.ts — server-side conversation fetch + feedback submission
  types/index.ts    — TypeScript types (ConversationFolder, UploadedFile, NegativeFeedbackReason, etc.)

frontend/
  eslint.config.js  — ESLint 9 flat config (TypeScript + React hooks + React Refresh)
  .dockerignore     — excludes node_modules, dist, tests

k6/                 — k6 load test scripts (smoke, load, stress)
k8s/                — Kubernetes manifests (namespace, backend+HPA, worker, infra, ingress+WAF, config)
secrets/            — Container secrets directory (gitignored, mounted read-only)
.github/workflows/ci.yml — CI/CD pipeline (tests, lint, container build+scan, GHCR push, K8s deploy)
```
