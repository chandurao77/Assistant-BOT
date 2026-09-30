# =============================================================================
# Assistant Bot — Automated Backup Script (PowerShell)
# =============================================================================
# Usage:
#   .\backup.ps1                       -> backup SQLite + Qdrant snapshot
#   .\backup.ps1 -Restore <dir>        -> restore from a backup directory
#
# Backups are stored in ./backups/ with timestamped directories.
# =============================================================================
param(
    [string]$Restore = ""
)

$ErrorActionPreference = "Stop"
$ROOT = $PSScriptRoot
$BACKUP_DIR = Join-Path $ROOT "backups"
$TIMESTAMP = Get-Date -Format "yyyyMMdd_HHmmss"
$TARGET = Join-Path $BACKUP_DIR $TIMESTAMP

function OK   { param($m) Write-Host "  [OK] $m" -ForegroundColor Green  }
function INFO { param($m) Write-Host "  [..] $m" -ForegroundColor Cyan   }
function WARN { param($m) Write-Host "  [!!] $m" -ForegroundColor Yellow }
function FAIL { param($m) Write-Host "  [XX] $m" -ForegroundColor Red; exit 1 }

# --- RESTORE MODE ---
if ($Restore) {
    if (-not (Test-Path $Restore)) { FAIL "Restore directory not found: $Restore" }

    INFO "Restoring from $Restore ..."

    $dbFile = Join-Path $Restore "conversations.db"
    if (Test-Path $dbFile) {
        podman cp $dbFile "assistant-bot-backend:/app/data/conversations.db"
        OK "SQLite database restored."
    } else {
        WARN "No conversations.db found in backup."
    }

    $snap = Get-ChildItem -Path $Restore -Filter "*.snapshot" -File | Select-Object -First 1
    if ($snap) {
        $collection = "confluence_docs"
        INFO "Restoring Qdrant collection '$collection' from snapshot ..."
        curl -s -X POST "http://localhost:6333/collections/$collection/snapshots/upload" `
            -H "Content-Type: multipart/form-data" `
            -F "snapshot=@$($snap.FullName)" 2>$null | Out-Null
        OK "Qdrant snapshot restored."
    } else {
        WARN "No Qdrant snapshot found in backup."
    }

    INFO "Restarting backend to pick up restored data ..."
    Set-Location $ROOT
    podman compose restart backend | Out-Null
    OK "Restore complete."
    exit 0
}

# --- BACKUP MODE ---
Write-Host ""
Write-Host "=== Assistant Bot Backup - $TIMESTAMP ===" -ForegroundColor Magenta
Write-Host ""

New-Item -ItemType Directory -Path $TARGET -Force | Out-Null

# 1. Backup SQLite database
INFO "Backing up SQLite database ..."
try {
    podman cp "assistant-bot-backend:/app/data/conversations.db" (Join-Path $TARGET "conversations.db") 2>$null
    OK "SQLite backed up: $TARGET\conversations.db"
} catch {
    WARN "Could not backup SQLite (container may not be running)."
}

# 2. Backup Qdrant via snapshot API
INFO "Creating Qdrant collection snapshot ..."
$collection = "confluence_docs"
try {
    $snapResp = Invoke-RestMethod -Method Post -Uri "http://localhost:6333/collections/$collection/snapshots" -ErrorAction Stop
    $snapName = $snapResp.result.name
    if ($snapName) {
        Invoke-WebRequest -Uri "http://localhost:6333/collections/$collection/snapshots/$snapName" `
            -OutFile (Join-Path $TARGET $snapName) -ErrorAction Stop
        OK "Qdrant snapshot saved: $TARGET\$snapName"
    }
} catch {
    WARN "Could not create Qdrant snapshot (Qdrant may not be running)."
}

# 3. Backup .env structure (secrets redacted)
$envFile = Join-Path $ROOT ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match "^([^=]+)=") { "$($Matches[1])=***REDACTED***" } else { $_ }
    } | Set-Content (Join-Path $TARGET "env_keys.txt")
    OK "Environment key structure saved (secrets redacted)."
}

# 4. Prune old backups (keep last 7)
$allBackups = Get-ChildItem -Path $BACKUP_DIR -Directory | Sort-Object Name
if ($allBackups.Count -gt 7) {
    $pruneCount = $allBackups.Count - 7
    $allBackups | Select-Object -First $pruneCount | ForEach-Object {
        Remove-Item $_.FullName -Recurse -Force
    }
    OK "Pruned $pruneCount old backup(s) (keeping last 7)."
}

Write-Host ""
OK "Backup complete: $TARGET"
Write-Host ""
