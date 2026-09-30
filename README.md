# Assistant Bot — Your documentation assistant

Assistant Bot is a self-hosted question-answering assistant for your own documents. You ingest documents (Markdown, text, JSON, Word, or a Confluence export), and then ask questions in a chat UI. Answers are generated from the retrieved passages and come with source citations.

Everything runs locally. Answer generation and embeddings use models served by [Ollama](https://ollama.com), and vectors are stored in [Qdrant](https://qdrant.tech). No cloud API keys are needed and no document leaves your machine.

## Features

- **Retrieval-augmented answers** with streaming responses and clickable source citations.
- **Hybrid search**: vector similarity plus Okapi BM25 keyword scoring, merged with reciprocal rank fusion.
- **Quality steps**: query rewriting for vague questions, spell correction, LLM re-ranking, entity boosting, one-hop link expansion, and confidence-gated multi-hop retrieval.
- **Semantic cache** so repeated questions skip retrieval and generation.
- **Guardrails**: regex redaction of secrets and personal data in retrieved context, and input checks against prompt injection.
- **Multi-turn conversations** with folders, search, rename, export, and feedback (thumbs up/down).
- **Diagrams**: ask for a flowchart or sequence diagram and get a rendered Mermaid diagram.
- **Auth**: JWT login, optional API key, optional OIDC single sign-on, and space-level access control.
- **Operations**: rate limiting, circuit breaker on the LLM, health and Prometheus metrics endpoints, optional ELK, OpenTelemetry, Redis, PostgreSQL, and Kubernetes manifests.
- **IDE integration**: a small MCP server (`mcp_stdio_proxy.py`) lets an AI coding assistant search your documents.

## Stack

FastAPI (Python 3.11) · React + TypeScript + Vite + Tailwind · Qdrant · Ollama · SQLite or PostgreSQL · Podman/Docker Compose

## Quick start

### 1. Requirements

- [Podman](https://podman.io) with `podman compose`, or Docker with `docker compose` (replace `podman` with `docker` in the commands below).
- About 10 GB of free disk space for the default models, and 16 GB of RAM for the 12B chat model. On a smaller machine choose a lighter model (step 2).

### 2. Configure

```bash
cp .env.example .env
```

The defaults work as they are. To use a lighter chat model, edit `.env`:

```
OLLAMA_LLM_MODEL=llama3.2:3b
```

### 3. Start everything

```bash
./run.sh            # macOS / Linux
.\run.ps1           # Windows PowerShell
```

The script starts Qdrant, Ollama, the backend, and the frontend, and downloads the chat and embedding models on the first run (this can take a while). If you prefer to do it by hand:

```bash
podman compose up -d
podman compose exec ollama ollama pull mistral-nemo     # or the model in your .env
podman compose exec ollama ollama pull nomic-embed-text
```

### 4. Ingest the sample documents

The `test_docs/` folder contains sample documents for a fictional company ("Orbit Labs"): an engineering handbook, incident and on-call runbooks, API guidelines, a deployment runbook, security practices, an AI usage policy, an architecture overview, and a set of FAQs.

```bash
curl -X POST "http://localhost:8005/api/ingest/local?full_refresh=true"
```

Add `-H "X-API-Key: <your key>"` if you set `API_KEY` in `.env`. Check progress with `GET /api/ingest/status`.

To use your own documents, put them in `test_docs/` (`.md`, `.txt`, `.json`, `.docx`, or Confluence `.doc` exports) and ingest again. You can also upload files directly from the chat UI.

### 5. Ask questions

Open <http://localhost:3000>, create an account with the "Register" option on the sign-in screen, and try:

- "What are the API rate limits?"
- "When do production releases happen?"
- "Who becomes the Incident Commander by default?"
- "Draw a sequence diagram of how an order is created."
- "Which AI models can I use?"

| Service | URL |
|---------|-----|
| Web UI | <http://localhost:3000> |
| Backend API (Swagger docs) | <http://localhost:8005/api/docs> (development mode only) |
| Qdrant dashboard | <http://localhost:6333/dashboard> |
| Ollama | <http://localhost:11434> |

## Configuration

All settings are environment variables loaded from `.env`. [.env.example](.env.example) lists every option with comments. The most useful ones:

| Variable | Default | Purpose |
|----------|---------|---------|
| `OLLAMA_LLM_MODEL` | `mistral-nemo` | Chat model (any model available in Ollama) |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Embedding model (768 dimensions) |
| `RETRIEVAL_TOP_K` | `10` | Chunks retrieved per query |
| `RERANK_ENABLED` | `true` | LLM re-ranking of retrieved chunks |
| `SEMANTIC_CACHE_ENABLED` | `true` | Cache answers for similar questions |
| `CONTENT_GUARDRAIL_ENABLED` | `true` | Redact secrets and personal data in context |
| `API_KEY` | empty | Protects ingest endpoints when set |
| `DATABASE_URL` | SQLite | Set to a PostgreSQL URL to use PostgreSQL |

If you change the embedding model, set `QDRANT_VECTOR_SIZE` to its output size and re-ingest with `full_refresh=true`.

Optional importers for your own Confluence Cloud site, Jira, and GitHub are described in `.env.example` and are disabled by default.

## API overview

All routes are under `/api`.

| Area | Routes |
|------|--------|
| Chat | `POST /chat/stream` (server-sent events), `GET /chat/suggestions` |
| Conversations | `GET /conversations`, `GET/PATCH/DELETE /conversations/{id}`, `GET /conversations/{id}/export` |
| Ingest | `POST /ingest/local`, `POST /ingest/push-pages`, `POST /ingest` (Confluence), `/ingest/jira`, `/ingest/github`, `GET /ingest/status` |
| Upload | `POST /upload`, `DELETE /upload/{id}` |
| Feedback | `POST /feedback`, `GET /feedback/stats` |
| Auth | `POST /auth/register`, `POST /auth/login`, `GET /auth/me`, OIDC under `/auth/sso/*` |
| Health | `GET /health`, `/health/metrics`, `/health/spaces`, `/health/admin-stats` |

## Tests

```bash
# Backend
cd backend
pip install -r requirements.txt pytest pytest-asyncio
ENVIRONMENT=development python -m pytest tests/

# Frontend
cd frontend
npm install
npm test
```

Some backend tests that exercise the upload and feedback routes expect the container path `/app/data` and only pass inside the backend container (`make test-backend`).

## Project layout

```
backend/app/
  api/routes/     chat, ingest, upload, conversations, feedback, auth, health, integrations
  services/       rag.py (pipeline), llm.py, embeddings.py, vector_store.py, bm25.py,
                  reranker.py, query_rewriter.py, semantic_cache.py, content_guardrail.py, ...
  models/         request/response schemas
backend/tests/    pytest suite
frontend/src/     React app (chat, sidebar, admin dashboard)
test_docs/        sample documents
docs/             architecture and IDE-integration notes
k8s/, elk/, k6/   optional deployment, logging, and load-test assets
```

See [docs/architecture.md](docs/architecture.md) for how a question flows through the system and [docs/ide-integration.md](docs/ide-integration.md) for the MCP server.

## Notes

- Sample data is fictional. Any resemblance to a real organization is coincidental.
- The backend port is `8005` on the host (`8000` inside the container).
- Small models (3B and under) follow instructions less reliably: in testing, `llama3.2:3b` retrieved the right sources every time but sometimes wrapped answers in a diagram block or echoed the context. Use a 7B+ model such as `mistral-nemo` or `llama3.1:8b` for cleaner answers.
- First answers after startup are slow while Ollama loads the model into memory. CPU-only machines take noticeably longer than machines with a GPU.
