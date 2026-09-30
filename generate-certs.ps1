# =============================================================================
# Generate self-signed TLS certificates for local HTTPS development
# =============================================================================
# Usage:  .\generate-certs.ps1
# Output: certs/server.crt + certs/server.key
# Then:   podman compose --profile tls up -d
# Access: https://localhost (accept the self-signed cert warning)
# =============================================================================

$certsDir = Join-Path $PSScriptRoot "certs"
if (-not (Test-Path $certsDir)) {
    New-Item -ItemType Directory -Path $certsDir | Out-Null
}

$keyFile  = Join-Path $certsDir "server.key"
$certFile = Join-Path $certsDir "server.crt"

if (Test-Path $certFile) {
    Write-Host "  [OK] Certificates already exist in ./certs/" -ForegroundColor Green
    Write-Host "       Delete ./certs/ and re-run to regenerate." -ForegroundColor DarkGray
    exit 0
}

# Check for openssl
if (-not (Get-Command openssl -ErrorAction SilentlyContinue)) {
    Write-Host "  [!!] openssl not found. Install OpenSSL or Git for Windows (includes openssl)." -ForegroundColor Yellow
    Write-Host "       Alternatively, use Podman:" -ForegroundColor DarkGray
    Write-Host "       podman run --rm -v ${certsDir}:/certs alpine/openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout /certs/server.key -out /certs/server.crt -subj '/CN=localhost'" -ForegroundColor DarkGray
    exit 1
}

Write-Host "  [..] Generating self-signed certificate for localhost..." -ForegroundColor Cyan

openssl req -x509 -nodes -days 365 -newkey rsa:2048 `
    -keyout $keyFile `
    -out $certFile `
    -subj "/CN=localhost" `
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

if ($LASTEXITCODE -eq 0) {
    Write-Host "  [OK] Certificates generated:" -ForegroundColor Green
    Write-Host "       $certFile" -ForegroundColor White
    Write-Host "       $keyFile" -ForegroundColor White
    Write-Host ""
    Write-Host "  Next steps:" -ForegroundColor Cyan
    Write-Host "    1. podman compose --profile tls up -d" -ForegroundColor White
    Write-Host "    2. Open https://localhost" -ForegroundColor White
    Write-Host "    3. Accept the self-signed certificate warning" -ForegroundColor White
} else {
    Write-Host "  [XX] Certificate generation failed." -ForegroundColor Red
    exit 1
}
