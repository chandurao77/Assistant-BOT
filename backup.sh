#!/usr/bin/env bash
# =============================================================================
# Assistant Bot — Automated Backup Script
# =============================================================================
# Usage:
#   ./backup.sh                  -> backup SQLite + Qdrant snapshot
#   ./backup.sh --restore <dir>  -> restore from a backup directory
#
# Backups are stored in ./backups/ with timestamped directories.
# Recommended: run via cron daily:
#   0 2 * * * /path/to/Assistant-BOT/backup.sh >> /var/log/assistant-bot-backup.log 2>&1
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKUP_DIR="$ROOT/backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
TARGET="$BACKUP_DIR/$TIMESTAMP"

ok()   { echo -e "  \033[32m[OK]\033[0m $1"; }
info() { echo -e "  \033[36m[..]\033[0m $1"; }
warn() { echo -e "  \033[33m[!!]\033[0m $1"; }
fail() { echo -e "  \033[31m[XX]\033[0m $1"; exit 1; }

# --- RESTORE MODE ---
if [ "${1:-}" = "--restore" ] && [ -n "${2:-}" ]; then
    RESTORE_DIR="$2"
    [ -d "$RESTORE_DIR" ] || fail "Restore directory not found: $RESTORE_DIR"

    info "Restoring from $RESTORE_DIR ..."

    # Restore SQLite
    if [ -f "$RESTORE_DIR/conversations.db" ]; then
        podman cp "$RESTORE_DIR/conversations.db" assistant-bot-backend:/app/data/conversations.db
        ok "SQLite database restored."
    else
        warn "No conversations.db found in backup."
    fi

    # Restore Qdrant snapshot
    SNAP=$(find "$RESTORE_DIR" -name "*.snapshot" -type f | head -1)
    if [ -n "$SNAP" ]; then
        COLLECTION="confluence_docs"
        info "Restoring Qdrant collection '$COLLECTION' from snapshot ..."
        curl -s -X POST "http://localhost:6333/collections/$COLLECTION/snapshots/upload" \
            -H "Content-Type: multipart/form-data" \
            -F "snapshot=@$SNAP" || warn "Qdrant snapshot restore failed."
        ok "Qdrant snapshot restored."
    else
        warn "No Qdrant snapshot found in backup."
    fi

    info "Restarting backend to pick up restored data ..."
    cd "$ROOT" && podman compose restart backend
    ok "Restore complete."
    exit 0
fi

# --- BACKUP MODE ---
echo ""
echo "=== Assistant Bot Backup — $TIMESTAMP ==="
echo ""

mkdir -p "$TARGET"

# 1. Backup SQLite database
info "Backing up SQLite database ..."
podman cp assistant-bot-backend:/app/data/conversations.db "$TARGET/conversations.db" 2>/dev/null && \
    ok "SQLite backed up: $TARGET/conversations.db" || \
    warn "Could not backup SQLite (container may not be running)."

# 2. Backup Qdrant via snapshot API
info "Creating Qdrant collection snapshot ..."
COLLECTION="confluence_docs"
SNAP_RESP=$(curl -s -X POST "http://localhost:6333/collections/$COLLECTION/snapshots" 2>/dev/null || echo "")
SNAP_NAME=$(echo "$SNAP_RESP" | grep -o '"name":"[^"]*"' | head -1 | cut -d'"' -f4)

if [ -n "$SNAP_NAME" ]; then
    curl -s "http://localhost:6333/collections/$COLLECTION/snapshots/$SNAP_NAME" \
        -o "$TARGET/$SNAP_NAME" 2>/dev/null && \
        ok "Qdrant snapshot saved: $TARGET/$SNAP_NAME" || \
        warn "Could not download Qdrant snapshot."
else
    warn "Could not create Qdrant snapshot (Qdrant may not be running)."
fi

# 3. Backup .env (without secrets — just structure)
if [ -f "$ROOT/.env" ]; then
    # Strip actual secret values, keep keys
    sed 's/=.*/=***REDACTED***/' "$ROOT/.env" > "$TARGET/env_keys.txt"
    ok "Environment key structure saved (secrets redacted)."
fi

# 4. Prune old backups (keep last 7)
BACKUP_COUNT=$(find "$BACKUP_DIR" -maxdepth 1 -type d ! -path "$BACKUP_DIR" | wc -l)
if [ "$BACKUP_COUNT" -gt 7 ]; then
    PRUNE_COUNT=$((BACKUP_COUNT - 7))
    find "$BACKUP_DIR" -maxdepth 1 -type d ! -path "$BACKUP_DIR" | sort | head -n "$PRUNE_COUNT" | xargs rm -rf
    ok "Pruned $PRUNE_COUNT old backup(s) (keeping last 7)."
fi

echo ""
ok "Backup complete: $TARGET"
echo ""
