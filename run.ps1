# =============================================================================
# Assistant Bot -- Full Setup & Run Script
# =============================================================================
# Usage:
#   .\run.ps1              -> start everything (first time or restart)
#   .\run.ps1 -Test        -> start + run all tests
#   .\run.ps1 -Ingest      -> start + re-ingest local docs into Qdrant
#   .\run.ps1 -Rebuild     -> force Podman image rebuild then start
#   .\run.ps1 -NoCache     -> rebuild images from scratch (no layer cache)
#   .\run.ps1 -TLS         -> start with HTTPS (generates self-signed certs)
#   .\run.ps1 -ELK         -> start with ELK stack (Elasticsearch + Kibana)
#   .\run.ps1 -Postgres    -> start with PostgreSQL (instead of SQLite)
#   .\run.ps1 -LoadTest    -> run k6 smoke test against running services
#   .\run.ps1 -Stop        -> stop all containers
#   .\run.ps1 -Logs        -> tail live logs from all containers
#   .\run.ps1 -Status      -> show container health status
# =============================================================================
param(
    [switch]$Test,
    [switch]$Ingest,
    [switch]$Rebuild,
    [switch]$NoCache,
    [switch]$TLS,
    [switch]$ELK,
    [switch]$Postgres,
    [switch]$LoadTest,
    [switch]$Stop,
    [switch]$Logs,
    [switch]$Status
)

$ErrorActionPreference = "Stop"
$ROOT  = $PSScriptRoot
$BACK  = Join-Path $ROOT "backend"
$FRONT = Join-Path $ROOT "frontend"
$ENV   = Join-Path $ROOT ".env"
$ENVEX = Join-Path $BACK ".env.example"

function OK    { param($m) Write-Host "  [OK] $m" -ForegroundColor Green  }
function INFO  { param($m) Write-Host "  [..] $m" -ForegroundColor Cyan   }
function WARN  { param($m) Write-Host "  [!!] $m" -ForegroundColor Yellow }
function FAIL  { param($m) Write-Host "  [XX] $m" -ForegroundColor Red; exit 1 }
function TITLE { param($m) Write-Host "`n=== $m ===" -ForegroundColor Magenta }

# STOP
if ($Stop) {
    TITLE "Stopping all containers"
    Set-Location $ROOT
    podman compose down
    OK "All containers stopped."
    exit 0
}

# LOGS
if ($Logs) {
    TITLE "Tailing logs (Ctrl+C to exit)"
    Set-Location $ROOT
    podman compose logs -f
    exit 0
}

# STATUS
if ($Status) {
    TITLE "Container status"
    Set-Location $ROOT
    podman compose ps
    exit 0
}

# PREREQUISITES
TITLE "Checking prerequisites"
if (-not (Get-Command podman -ErrorAction SilentlyContinue)) {
    FAIL "Podman is not installed or not in PATH. Install Podman first."
}
podman info 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    INFO "Podman machine is not running. Starting it..."
    podman machine start
    if ($LASTEXITCODE -ne 0) { FAIL "Failed to start Podman machine." }
    OK "Podman machine started."
} else {
    OK "Podman is running."
}
$nodeOk = [bool](Get-Command node -ErrorAction SilentlyContinue)
if ($nodeOk) {
    OK "Node $(node --version) / npm $(npm --version) found."
} else {
    WARN "Node.js not found -- frontend tests will be skipped."
}

# ENV FILE
TITLE "Environment file"
if (-not (Test-Path $ENV)) {
    INFO ".env not found -- copying from .env.example (auto-approved)."
    Copy-Item $ENVEX $ENV
    $c = Get-Content $ENV -Raw
    $c = $c -replace "OLLAMA_TIMEOUT=120", "OLLAMA_CONNECT_TIMEOUT=10`nOLLAMA_READ_TIMEOUT=120"
    Set-Content $ENV $c
    WARN "Created .env -- review Confluence credentials before ingesting from Confluence."
    OK ".env ready."
} else {
    $c = Get-Content $ENV -Raw
    if ($c -match "OLLAMA_TIMEOUT=" -and $c -notmatch "OLLAMA_CONNECT_TIMEOUT=") {
        INFO "Migrating OLLAMA_TIMEOUT to split timeout keys (auto)."
        $c = $c -replace "OLLAMA_TIMEOUT=\d+", "OLLAMA_CONNECT_TIMEOUT=10`nOLLAMA_READ_TIMEOUT=120"
        Set-Content $ENV $c
        OK ".env migrated."
    } else {
        OK ".env exists and is up to date."
    }
}

# BUILD & START
TITLE "Starting Podman containers"
Set-Location $ROOT

# TLS mode: generate certs and use --profile tls
$composeProfile = @()
if ($TLS) {
    INFO "TLS mode enabled — checking certificates..."
    $certsDir = Join-Path $ROOT "certs"
    if (-not (Test-Path (Join-Path $certsDir "server.crt"))) {
        INFO "Generating self-signed certificates..."
        & (Join-Path $ROOT "generate-certs.ps1")
        if ($LASTEXITCODE -ne 0) { FAIL "Certificate generation failed." }
    } else {
        OK "Certificates found in ./certs/"
    }
    $composeProfile = @("--profile", "tls")
}

# In TLS mode, fully remove the non-TLS frontend first to free port 3000
if ($TLS) {
    INFO "Removing non-TLS frontend to avoid port conflict..."
    podman compose rm -sf frontend 2>$null | Out-Null
}

# ELK mode: enable observability stack
if ($ELK) {
    INFO "ELK stack enabled — Elasticsearch + Logstash + Kibana + Filebeat"
    $composeProfile += @("--profile", "elk")
    # Enable log shipping from backend to Logstash
    $envContent = Get-Content $ENV -Raw -ErrorAction SilentlyContinue
    if ($envContent -notmatch "ELK_ENABLED") {
        Add-Content -Path $ENV -Value "`nELK_ENABLED=true"
    }
}

# PostgreSQL mode: use PostgreSQL instead of SQLite
if ($Postgres) {
    INFO "PostgreSQL mode enabled — using PostgreSQL for conversation store"
    $composeProfile += @("--profile", "postgres")
    $envContent = Get-Content $ENV -Raw -ErrorAction SilentlyContinue
    if ($envContent -notmatch "DATABASE_URL") {
        Add-Content -Path $ENV -Value "`nDATABASE_URL=postgresql+asyncpg://assistant_bot:assistant_bot@postgres:5432/assistant_bot"
    }
}

$scaleArgs = @()
if ($TLS) { $scaleArgs = @("--scale", "frontend=0") }

if ($NoCache) {
    INFO "Rebuilding images from scratch (--no-cache)."
    podman compose @composeProfile build --no-cache
    podman compose @composeProfile up -d @scaleArgs
    # Flush the semantic cache so stale answers are not served
    INFO "Clearing semantic cache (Qdrant) ..."
    Start-Sleep -Seconds 5  # wait for qdrant to be ready
    podman compose exec -T backend python -c "from qdrant_client import QdrantClient; c = QdrantClient(host='qdrant', port=6333); colls = [x.name for x in c.get_collections().collections]; c.delete_collection('semantic_cache') if 'semantic_cache' in colls else None; print('semantic_cache cleared')" 2>$null
    if ($LASTEXITCODE -eq 0) { OK "Semantic cache cleared." } else { WARN "Could not clear semantic cache -- it will be rebuilt on first query." }
} elseif ($Rebuild) {
    INFO "Rebuilding images (--build flag set)."
    podman compose @composeProfile up -d --build @scaleArgs
} else {
    $img = podman images ai-assistant-bot-backend -q 2>$null
    if (-not $img) {
        INFO "Backend image not found -- building for the first time."
        podman compose @composeProfile up -d --build @scaleArgs
    } else {
        INFO "Images exist -- starting containers without rebuild."
        podman compose @composeProfile up -d @scaleArgs
    }
}
if ($LASTEXITCODE -ne 0) { FAIL "podman compose up failed." }
OK "Containers started."

# WAIT FOR HEALTH
TITLE "Waiting for services to become healthy"
$services = @("assistant-bot-backend", "assistant-bot-qdrant")
if ($TLS) {
    $services += "assistant-bot-frontend-tls"
} else {
    $services += "assistant-bot-frontend"
}
$maxWait  = 120
$interval = 5
foreach ($svc in $services) {
    $waited = 0
    INFO "Waiting for $svc ..."
    while ($waited -lt $maxWait) {
        $hc      = podman inspect --format "{{.State.Health.Status}}" $svc 2>$null
        $running = podman inspect --format "{{.State.Running}}" $svc 2>$null
        if ($hc -eq "healthy") { OK "$svc is healthy."; break }
        if ($running -eq "true" -and [string]::IsNullOrEmpty($hc)) { OK "$svc is running (no healthcheck)."; break }
        Start-Sleep -Seconds $interval
        $waited += $interval
        INFO "  $svc status: $hc ($waited s / $maxWait s)"
    }
    if ($waited -ge $maxWait) {
        WARN "$svc did not become healthy in $($maxWait)s -- check: podman logs $svc"
    }
}

# INJECT HOST CA CERTS INTO OLLAMA (corporate proxy support)
TITLE "Configuring TLS certificates for Ollama"
$certInjected = $false

# Auto-export host CA certificates so model pulls work behind corporate proxies
try {
    $tempCert = Join-Path $env:TEMP "host-ca-certs.pem"
    $certs = Get-ChildItem Cert:\LocalMachine\Root
    $pemLines = @()
    foreach ($cert in $certs) {
        $pemLines += "-----BEGIN CERTIFICATE-----"
        $pemLines += [Convert]::ToBase64String($cert.RawData, 'InsertLineBreaks')
        $pemLines += "-----END CERTIFICATE-----"
    }
    Set-Content -Path $tempCert -Value ($pemLines -join "`n") -Encoding ASCII
    podman cp $tempCert "assistant-bot-ollama:/usr/local/share/ca-certificates/host-ca.crt" 2>$null | Out-Null
    podman exec assistant-bot-ollama update-ca-certificates 2>$null | Out-Null
    $certInjected = $true
    Remove-Item $tempCert -ErrorAction SilentlyContinue
} catch {
    # Cert export from Windows store failed -- try local file fallback
}

# Also check for a project-local corporate CA cert file
$localCert = Join-Path $ROOT "corporate-ca.crt"
if (Test-Path $localCert) {
    podman cp $localCert "assistant-bot-ollama:/usr/local/share/ca-certificates/corporate-ca.crt" 2>$null | Out-Null
    podman exec assistant-bot-ollama update-ca-certificates 2>$null | Out-Null
    $certInjected = $true
}

if ($certInjected) {
    OK "Host CA certificates injected into Ollama container."
} else {
    WARN "Could not inject host CA certs -- model pulls may fail behind corporate proxy."
    INFO "To fix: place your corporate CA cert at $ROOT\corporate-ca.crt and re-run."
}

# OLLAMA MODELS
TITLE "Checking Ollama models"
$llmModel   = "mistral"
$embedModel = "nomic-embed-text"
foreach ($line in (Get-Content $ENV)) {
    if ($line -match "^OLLAMA_LLM_MODEL=(.+)")   { $llmModel   = $Matches[1].Trim() }
    if ($line -match "^OLLAMA_EMBED_MODEL=(.+)") { $embedModel = $Matches[1].Trim() }
}
$pulled = podman compose exec -T ollama ollama list 2>$null
foreach ($model in @($llmModel, $embedModel)) {
    $escaped = [regex]::Escape($model)
    if ($pulled -match $escaped) {
        OK "Model '$model' already downloaded -- skipping pull."
    } else {
        INFO "Pulling model '$model' (may take several minutes on first run) ..."
        podman compose exec -T ollama ollama pull $model
        if ($LASTEXITCODE -ne 0) {
            WARN "Failed to pull '$model' -- the app may not answer until it is available."
        } else {
            OK "Model '$model' downloaded."
        }
    }
}

# SYNC SOURCE FILES
TITLE "Syncing source files to backend container"
$files = @(
    "app/config.py",
    "app/main.py",
    "app/api/routes/chat.py",
    "app/api/routes/ingest.py",
    "app/api/routes/conversations.py",
    "app/api/routes/feedback.py",
    "app/api/routes/upload.py",
    "app/api/routes/auth.py",
    "app/api/dependencies.py",
    "app/services/llm.py",
    "app/services/rag.py",
    "app/services/embeddings.py",
    "app/services/vector_store.py",
    "app/services/conversation_store.py",
    "app/services/pg_conversation_store.py",
    "app/services/semantic_cache.py",
    "app/services/content_guardrail.py",
    "app/services/auth.py",
    "app/services/entity_store.py",
    "app/services/reranker.py",
    "app/services/redis_cache.py",
    "app/services/slack_bot.py",
    "app/services/teams_bot.py",
    "app/services/atlassian_token_rotation.py",
    "app/api/routes/integrations.py"
)
Push-Location $BACK
foreach ($f in $files) {
    if (Test-Path $f) {
        podman cp $f "assistant-bot-backend:/app/$f" 2>$null | Out-Null
    }
}
if (Test-Path "tests") {
    podman cp "tests" "assistant-bot-backend:/app/" 2>$null | Out-Null
}
Pop-Location
OK "Source files synced."

INFO "Restarting backend to apply changes ..."
podman compose restart backend | Out-Null
Start-Sleep -Seconds 8
$waited = 0
while ($waited -lt 60) {
    $hc = podman inspect --format "{{.State.Health.Status}}" assistant-bot-backend 2>$null
    if ($hc -eq "healthy") { OK "Backend is healthy after restart."; break }
    Start-Sleep -Seconds 5
    $waited += 5
}
if ($waited -ge 60) { WARN "Backend restart taking longer than expected." }

# INGESTION
TITLE "Document ingestion"
if ($Ingest) {
    INFO "Running full-refresh ingestion of local test docs ..."
    try {
        $r = Invoke-RestMethod `
            -Method Post `
            -Uri "http://localhost:8005/api/ingest/local" `
            -ContentType "application/json" `
            -Body '{"full_refresh": true}'
        OK "Ingestion complete: $($r.chunks_indexed) chunks from $($r.pages_processed) pages."
    } catch {
        WARN "Ingestion failed: $($_.Exception.Message)"
        WARN "Check logs: podman logs assistant-bot-backend"
    }
} else {
    try {
        $h = Invoke-RestMethod -Uri "http://localhost:8005/api/health" -ErrorAction Stop
        if ($h.qdrant_docs -eq 0) {
            INFO "Qdrant is empty -- running initial ingestion (auto-approved)."
            Invoke-RestMethod `
                -Method Post `
                -Uri "http://localhost:8005/api/ingest/local" `
                -ContentType "application/json" `
                -Body '{"full_refresh": false}' | Out-Null
            OK "Initial ingestion triggered."
        } else {
            OK "Qdrant already has $($h.qdrant_docs) docs -- skipping ingestion."
        }
    } catch {
        WARN "Could not check Qdrant doc count -- skipping auto-ingest."
        WARN "Use:  .\run.ps1 -Ingest  to force ingestion."
    }
}

# TESTS
if ($Test) {
    TITLE "Running backend tests (pytest)"
    podman compose exec -T backend sh -c "cd /app && python -m pytest tests/ -v 2>&1"
    if ($LASTEXITCODE -eq 0) {
        OK "All backend tests passed."
    } else {
        WARN "Some backend tests failed -- see output above."
    }
    if ($nodeOk) {
        TITLE "Running frontend tests (vitest)"
        Push-Location $FRONT
        if (-not (Test-Path "node_modules")) {
            INFO "node_modules missing -- running npm install (auto-approved)."
            npm install --silent
        }
        npm test -- --run
        if ($LASTEXITCODE -eq 0) {
            OK "All frontend tests passed."
        } else {
            WARN "Some frontend tests failed -- see output above."
        }
        Pop-Location
    } else {
        WARN "Skipping frontend tests (Node.js not installed)."
    }
}

# LOAD TEST (k6)
if ($LoadTest) {
    TITLE "Running k6 smoke test"
    INFO "Running smoke test against backend..."
    podman compose --profile loadtest run --rm k6 run /scripts/smoke-test.js
    if ($LASTEXITCODE -eq 0) {
        OK "k6 smoke test passed."
    } else {
        WARN "k6 smoke test had failures -- see output above."
    }
    INFO "For full load / stress tests, run manually:"
    INFO "  podman compose --profile loadtest run --rm k6 run /scripts/load-test.js"
    INFO "  podman compose --profile loadtest run --rm k6 run /scripts/stress-test.js"
}

# DONE
TITLE "Ready"
Write-Host ""
if ($TLS) {
    Write-Host "  App (HTTPS) ->  https://127.0.0.1"             -ForegroundColor White
} else {
    Write-Host "  App       ->  http://127.0.0.1:3000"           -ForegroundColor White
}
Write-Host "  API docs  ->  http://localhost:8005/api/docs"  -ForegroundColor White
Write-Host "  Qdrant    ->  http://localhost:6333/dashboard"  -ForegroundColor White
if ($ELK) {
    Write-Host "  Kibana    ->  http://localhost:5601"           -ForegroundColor White
    Write-Host "  Elastic   ->  http://localhost:9200"           -ForegroundColor White
}
Write-Host ""
Write-Host "  Commands:"                                      -ForegroundColor DarkGray
Write-Host "    .\run.ps1 -Status   -> container health"     -ForegroundColor DarkGray
Write-Host "    .\run.ps1 -Logs     -> live logs"            -ForegroundColor DarkGray
Write-Host "    .\run.ps1 -Test     -> run all tests"        -ForegroundColor DarkGray
Write-Host "    .\run.ps1 -Ingest   -> re-ingest local docs" -ForegroundColor DarkGray
Write-Host "    .\run.ps1 -Rebuild  -> rebuild images"       -ForegroundColor DarkGray
Write-Host "    .\run.ps1 -TLS      -> start with HTTPS"     -ForegroundColor DarkGray
Write-Host "    .\run.ps1 -ELK      -> start with ELK"       -ForegroundColor DarkGray
Write-Host "    .\run.ps1 -Postgres -> start with PostgreSQL"  -ForegroundColor DarkGray
Write-Host "    .\run.ps1 -LoadTest -> run k6 load tests"      -ForegroundColor DarkGray
Write-Host "    .\run.ps1 -Stop     -> stop everything"      -ForegroundColor DarkGray
Write-Host ""
