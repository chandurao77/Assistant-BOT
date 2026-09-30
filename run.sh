#!/usr/bin/env bash
# =============================================================================
# Assistant Bot -- Full Setup & Run Script
# =============================================================================
# Usage:
#   ./run.sh              -> start everything (first time or restart)
#   ./run.sh --test       -> start + run all tests
#   ./run.sh --ingest     -> start + re-ingest local docs into Qdrant
#   ./run.sh --rebuild    -> force Podman image rebuild then start
#   ./run.sh --tls        -> start with HTTPS (generates self-signed certs)
#   ./run.sh --elk        -> start with ELK stack (Elasticsearch + Kibana)
#   ./run.sh --postgres   -> start with PostgreSQL (instead of SQLite)
#   ./run.sh --loadtest   -> run k6 smoke test against running services
#   ./run.sh --stop       -> stop all containers
#   ./run.sh --logs       -> tail live logs from all containers
#   ./run.sh --status     -> show container health status
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACK="$ROOT/backend"
FRONT="$ROOT/frontend"
ENV_FILE="$ROOT/.env"
ENV_EXAMPLE="$BACK/.env.example"

# --- Color helpers ---
ok()    { echo -e "  \033[32m[OK]\033[0m $1"; }
info()  { echo -e "  \033[36m[..]\033[0m $1"; }
warn()  { echo -e "  \033[33m[!!]\033[0m $1"; }
fail()  { echo -e "  \033[31m[XX]\033[0m $1"; exit 1; }
title() { echo -e "\n\033[35m=== $1 ===\033[0m"; }

# --- Parse flags ---
DO_TEST=false
DO_INGEST=false
DO_REBUILD=false
DO_TLS=false
DO_ELK=false
DO_POSTGRES=false
DO_LOADTEST=false
DO_STOP=false
DO_LOGS=false
DO_STATUS=false

for arg in "$@"; do
    case "$arg" in
        --test)    DO_TEST=true    ;;
        --ingest)  DO_INGEST=true  ;;
        --rebuild) DO_REBUILD=true ;;
        --tls)     DO_TLS=true     ;;
        --elk)     DO_ELK=true     ;;
        --postgres) DO_POSTGRES=true ;;
        --loadtest) DO_LOADTEST=true ;;
        --stop)    DO_STOP=true    ;;
        --logs)    DO_LOGS=true    ;;
        --status)  DO_STATUS=true  ;;
        *) warn "Unknown flag: $arg" ;;
    esac
done

# --- STOP ---
if $DO_STOP; then
    title "Stopping all containers"
    cd "$ROOT"
    podman compose down
    ok "All containers stopped."
    exit 0
fi

# --- LOGS ---
if $DO_LOGS; then
    title "Tailing logs (Ctrl+C to exit)"
    cd "$ROOT"
    podman compose logs -f
    exit 0
fi

# --- STATUS ---
if $DO_STATUS; then
    title "Container status"
    cd "$ROOT"
    podman compose ps
    exit 0
fi

# --- PREREQUISITES ---
title "Checking prerequisites"
if ! command -v podman &>/dev/null; then
    fail "Podman is not installed or not in PATH."
fi
if ! podman info &>/dev/null; then
    fail "Podman machine is not running. Start it with: podman machine start"
fi
ok "Podman is running."

NODE_OK=false
if command -v node &>/dev/null; then
    NODE_OK=true
    ok "Node $(node --version) / npm $(npm --version) found."
else
    warn "Node.js not found -- frontend tests will be skipped."
fi

# --- ENV FILE ---
title "Environment file"
if [ ! -f "$ENV_FILE" ]; then
    info ".env not found -- copying from .env.example."
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    sed -i.bak 's/OLLAMA_TIMEOUT=120/OLLAMA_CONNECT_TIMEOUT=10\nOLLAMA_READ_TIMEOUT=120/' "$ENV_FILE" 2>/dev/null || true
    rm -f "$ENV_FILE.bak"
    warn "Created .env -- review Confluence credentials before ingesting."
    ok ".env ready."
else
    if grep -q "OLLAMA_TIMEOUT=" "$ENV_FILE" && ! grep -q "OLLAMA_CONNECT_TIMEOUT=" "$ENV_FILE"; then
        info "Migrating OLLAMA_TIMEOUT to split timeout keys."
        sed -i.bak 's/OLLAMA_TIMEOUT=[0-9]*/OLLAMA_CONNECT_TIMEOUT=10\nOLLAMA_READ_TIMEOUT=120/' "$ENV_FILE"
        rm -f "$ENV_FILE.bak"
        ok ".env migrated."
    else
        ok ".env exists and is up to date."
    fi
fi

# --- BUILD & START ---
title "Starting Podman containers"
cd "$ROOT"

COMPOSE_PROFILE=()
SCALE_ARGS=()

if $DO_TLS; then
    info "TLS mode enabled — checking certificates..."
    if [ ! -f "$ROOT/certs/server.crt" ]; then
        info "Generating self-signed certificates..."
        bash "$ROOT/generate-certs.sh"
    else
        ok "Certificates found in ./certs/"
    fi
    COMPOSE_PROFILE=(--profile tls)
    info "Removing non-TLS frontend to avoid port conflict..."
    podman compose rm -sf frontend 2>/dev/null || true
    SCALE_ARGS=(--scale frontend=0)
fi

if $DO_ELK; then
    info "ELK stack enabled — Elasticsearch + Logstash + Kibana + Filebeat"
    COMPOSE_PROFILE+=("--profile" "elk")
    # Enable log shipping from backend to Logstash
    if ! grep -q "ELK_ENABLED" "$ENV_FILE" 2>/dev/null; then
        echo "ELK_ENABLED=true" >> "$ENV_FILE"
    fi
fi

if $DO_POSTGRES; then
    info "PostgreSQL mode enabled — using PostgreSQL for conversation store"
    COMPOSE_PROFILE+=("--profile" "postgres")
    if ! grep -q "DATABASE_URL" "$ENV_FILE" 2>/dev/null; then
        echo "DATABASE_URL=postgresql+asyncpg://assistant_bot:assistant_bot@postgres:5432/assistant_bot" >> "$ENV_FILE"
    fi
fi

if $DO_REBUILD; then
    info "Rebuilding images (--build flag set)."
    podman compose ${COMPOSE_PROFILE[@]+"${COMPOSE_PROFILE[@]}"} up -d --build ${SCALE_ARGS[@]+"${SCALE_ARGS[@]}"}
else
    IMG=$(podman images ai-assistant-bot-backend -q 2>/dev/null || true)
    if [ -z "$IMG" ]; then
        info "Backend image not found -- building for the first time."
        podman compose ${COMPOSE_PROFILE[@]+"${COMPOSE_PROFILE[@]}"} up -d --build ${SCALE_ARGS[@]+"${SCALE_ARGS[@]}"}
    else
        info "Images exist -- starting containers without rebuild."
        podman compose ${COMPOSE_PROFILE[@]+"${COMPOSE_PROFILE[@]}"} up -d ${SCALE_ARGS[@]+"${SCALE_ARGS[@]}"}
    fi
fi
ok "Containers started."

# --- WAIT FOR HEALTH ---
title "Waiting for services to become healthy"
SERVICES=("assistant-bot-backend" "assistant-bot-qdrant")
if $DO_TLS; then
    SERVICES+=("assistant-bot-frontend-tls")
else
    SERVICES+=("assistant-bot-frontend")
fi
MAX_WAIT=120
INTERVAL=5

for svc in "${SERVICES[@]}"; do
    waited=0
    info "Waiting for $svc ..."
    while [ $waited -lt $MAX_WAIT ]; do
        hc=$(podman inspect --format '{{.State.Health.Status}}' "$svc" 2>/dev/null || echo "")
        running=$(podman inspect --format '{{.State.Running}}' "$svc" 2>/dev/null || echo "false")
        if [ "$hc" = "healthy" ]; then ok "$svc is healthy."; break; fi
        if [ "$running" = "true" ] && [ -z "$hc" ]; then ok "$svc is running (no healthcheck)."; break; fi
        sleep $INTERVAL
        waited=$((waited + INTERVAL))
        info "  $svc status: $hc (${waited}s / ${MAX_WAIT}s)"
    done
    if [ $waited -ge $MAX_WAIT ]; then
        warn "$svc did not become healthy in ${MAX_WAIT}s -- check: podman logs $svc"
    fi
done

# --- INJECT HOST CA CERTS INTO OLLAMA (corporate proxy support) ---
title "Configuring TLS certificates for Ollama"
CERT_INJECTED=false

# Auto-export host CA certificates so model pulls work behind corporate proxies
if [[ "$(uname)" == "Darwin" ]]; then
    # macOS: export certs from System Keychain
    TEMP_CERTS=$(mktemp)
    security find-certificate -a -p /System/Library/Keychains/SystemRootCertificates.keychain > "$TEMP_CERTS" 2>/dev/null || true
    security find-certificate -a -p /Library/Keychains/System.keychain >> "$TEMP_CERTS" 2>/dev/null || true
    if [ -s "$TEMP_CERTS" ]; then
        podman cp "$TEMP_CERTS" assistant-bot-ollama:/usr/local/share/ca-certificates/host-ca.crt 2>/dev/null && \
        podman exec assistant-bot-ollama update-ca-certificates 2>/dev/null && \
        CERT_INJECTED=true
    fi
    rm -f "$TEMP_CERTS"
elif [ -f /etc/ssl/certs/ca-certificates.crt ]; then
    # Linux: copy system CA bundle
    podman cp /etc/ssl/certs/ca-certificates.crt assistant-bot-ollama:/usr/local/share/ca-certificates/host-ca.crt 2>/dev/null && \
    podman exec assistant-bot-ollama update-ca-certificates 2>/dev/null && \
    CERT_INJECTED=true
fi

# Also check for a project-local corporate CA cert file
if [ -f "$ROOT/corporate-ca.crt" ]; then
    podman cp "$ROOT/corporate-ca.crt" assistant-bot-ollama:/usr/local/share/ca-certificates/corporate-ca.crt 2>/dev/null && \
    podman exec assistant-bot-ollama update-ca-certificates 2>/dev/null && \
    CERT_INJECTED=true
fi

if $CERT_INJECTED; then
    ok "Host CA certificates injected into Ollama container."
else
    warn "Could not inject host CA certs -- model pulls may fail behind corporate proxy."
    info "To fix: place your corporate CA cert at $ROOT/corporate-ca.crt and re-run."
fi

# --- OLLAMA MODELS ---
title "Checking Ollama models"
LLM_MODEL="mistral"
EMBED_MODEL="nomic-embed-text"
while IFS= read -r line; do
    [[ "$line" =~ ^OLLAMA_LLM_MODEL=(.+) ]] && LLM_MODEL="${BASH_REMATCH[1]}"
    [[ "$line" =~ ^OLLAMA_EMBED_MODEL=(.+) ]] && EMBED_MODEL="${BASH_REMATCH[1]}"
done < "$ENV_FILE"

PULLED=$(podman compose exec -T ollama ollama list 2>/dev/null || true)
for model in "$LLM_MODEL" "$EMBED_MODEL"; do
    if echo "$PULLED" | grep -q "$model"; then
        ok "Model '$model' already downloaded -- skipping pull."
    else
        info "Pulling model '$model' (may take several minutes on first run) ..."
        if podman compose exec -T ollama ollama pull "$model"; then
            ok "Model '$model' downloaded."
        else
            warn "Failed to pull '$model' -- the app may not answer until it is available."
        fi
    fi
done

# --- SYNC SOURCE FILES ---
title "Syncing source files to backend container"
FILES=(
    "app/config.py"
    "app/main.py"
    "app/api/routes/chat.py"
    "app/api/routes/ingest.py"
    "app/api/routes/conversations.py"
    "app/api/routes/feedback.py"
    "app/api/routes/upload.py"
    "app/api/routes/auth.py"
    "app/api/dependencies.py"
    "app/services/llm.py"
    "app/services/rag.py"
    "app/services/embeddings.py"
    "app/services/vector_store.py"
    "app/services/conversation_store.py"
    "app/services/pg_conversation_store.py"
    "app/services/semantic_cache.py"
    "app/services/content_guardrail.py"
    "app/services/auth.py"
    "app/services/entity_store.py"
    "app/services/reranker.py"
    "app/services/redis_cache.py"
)

cd "$BACK"
for f in "${FILES[@]}"; do
    [ -f "$f" ] && podman cp "$f" "assistant-bot-backend:/app/$f" 2>/dev/null || true
done
[ -d "tests" ] && podman cp "tests" "assistant-bot-backend:/app/" 2>/dev/null || true
cd "$ROOT"
ok "Source files synced."

info "Restarting backend to apply changes ..."
podman compose restart backend >/dev/null
sleep 8
waited=0
while [ $waited -lt 60 ]; do
    hc=$(podman inspect --format '{{.State.Health.Status}}' assistant-bot-backend 2>/dev/null || echo "")
    if [ "$hc" = "healthy" ]; then ok "Backend is healthy after restart."; break; fi
    sleep 5
    waited=$((waited + 5))
done
if [ $waited -ge 60 ]; then warn "Backend restart taking longer than expected."; fi

# --- INGESTION ---
title "Document ingestion"
if $DO_INGEST; then
    info "Running full-refresh ingestion of local test docs ..."
    RESP=$(curl -s -X POST http://localhost:8000/api/ingest/local \
        -H "Content-Type: application/json" \
        -d '{"full_refresh": true}')
    if echo "$RESP" | grep -q "chunks_indexed"; then
        ok "Ingestion complete: $RESP"
    else
        warn "Ingestion may have failed: $RESP"
        warn "Check logs: podman logs assistant-bot-backend"
    fi
else
    HEALTH=$(curl -s http://localhost:8000/api/health 2>/dev/null || echo "{}")
    DOCS=$(echo "$HEALTH" | grep -o '"qdrant_docs":[0-9]*' | grep -o '[0-9]*' || echo "")
    if [ "$DOCS" = "0" ] || [ -z "$DOCS" ]; then
        info "Qdrant is empty -- running initial ingestion."
        curl -s -X POST http://localhost:8000/api/ingest/local \
            -H "Content-Type: application/json" \
            -d '{"full_refresh": false}' >/dev/null 2>&1 || true
        ok "Initial ingestion triggered."
    else
        ok "Qdrant already has $DOCS docs -- skipping ingestion."
    fi
fi

# --- TESTS ---
if $DO_TEST; then
    title "Running backend tests (pytest)"
    podman compose exec -T backend sh -c "cd /app && python -m pytest tests/ -v" && \
        ok "All backend tests passed." || \
        warn "Some backend tests failed -- see output above."

    if $NODE_OK; then
        title "Running frontend tests (vitest)"
        cd "$FRONT"
        [ ! -d "node_modules" ] && { info "Installing npm dependencies..."; npm install --silent; }
        npm test -- --run && \
            ok "All frontend tests passed." || \
            warn "Some frontend tests failed -- see output above."
        cd "$ROOT"
    else
        warn "Skipping frontend tests (Node.js not installed)."
    fi
fi

# --- LOAD TEST (k6) ---
if $DO_LOADTEST; then
    title "Running k6 smoke test"
    info "Running smoke test against backend..."
    if podman compose --profile loadtest run --rm k6 run /scripts/smoke-test.js; then
        ok "k6 smoke test passed."
    else
        warn "k6 smoke test had failures -- see output above."
    fi
    info "For full load / stress tests, run manually:"
    info "  podman compose --profile loadtest run --rm k6 run /scripts/load-test.js"
    info "  podman compose --profile loadtest run --rm k6 run /scripts/stress-test.js"
fi

# --- DONE ---
title "Ready"
echo ""
if $DO_TLS; then
    echo "  App (HTTPS) ->  https://127.0.0.1"
else
    echo "  App       ->  http://127.0.0.1:3000"
fi
echo "  API docs  ->  http://localhost:8000/api/docs"
echo "  Qdrant    ->  http://localhost:6333/dashboard"
if $DO_ELK; then
    echo "  Kibana    ->  http://localhost:5601"
    echo "  Elastic   ->  http://localhost:9200"
fi
echo ""
echo "  Commands:"
echo "    ./run.sh --status   -> container health"
echo "    ./run.sh --logs     -> live logs"
echo "    ./run.sh --test     -> run all tests"
echo "    ./run.sh --ingest   -> re-ingest local docs"
echo "    ./run.sh --rebuild  -> rebuild images"
echo "    ./run.sh --tls      -> start with HTTPS"
echo "    ./run.sh --elk      -> start with ELK observability"
echo "    ./run.sh --postgres -> start with PostgreSQL"
echo "    ./run.sh --loadtest -> run k6 load tests"
echo "    ./run.sh --stop     -> stop everything"
echo ""
