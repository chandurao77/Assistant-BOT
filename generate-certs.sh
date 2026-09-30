#!/usr/bin/env bash
# =============================================================================
# Generate self-signed TLS certificates for local HTTPS development
# =============================================================================
# Usage:  ./generate-certs.sh
# Output: certs/server.crt + certs/server.key
# Then:   podman compose --profile tls up -d
# Access: https://localhost (accept the self-signed cert warning)
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
CERTS_DIR="$ROOT/certs"

mkdir -p "$CERTS_DIR"

if [ -f "$CERTS_DIR/server.crt" ]; then
    echo "  [OK] Certificates already exist in ./certs/"
    echo "       Delete ./certs/ and re-run to regenerate."
    exit 0
fi

# Check for openssl
if command -v openssl &>/dev/null; then
    echo "  [..] Generating self-signed certificate for localhost..."
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout "$CERTS_DIR/server.key" \
        -out "$CERTS_DIR/server.crt" \
        -subj "/CN=localhost" \
        -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
else
    echo "  [..] openssl not found locally — using Podman..."
    podman run --rm -v "$CERTS_DIR:/certs" alpine/openssl \
        req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout /certs/server.key -out /certs/server.crt \
        -subj "/CN=localhost"
fi

echo "  [OK] Certificates generated:"
echo "       $CERTS_DIR/server.crt"
echo "       $CERTS_DIR/server.key"
echo ""
echo "  Next steps:"
echo "    1. podman compose --profile tls up -d"
echo "    2. Open https://localhost"
echo "    3. Accept the self-signed certificate warning"
