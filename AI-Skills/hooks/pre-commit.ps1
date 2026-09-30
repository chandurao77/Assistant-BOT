# Pre-commit hook (PowerShell)
# Orchestrates all validation hooks before commit.
# Install: Copy-Item hooks\pre-commit.ps1 .git\hooks\pre-commit.ps1

param()

$ErrorActionPreference = 'Continue'
$HooksDir = $PSScriptRoot
$CheckErrors = 0

Write-Host "==================================="
Write-Host "  Pre-Commit Checks"
Write-Host "==================================="

# Get staged files
$StagedFiles = git diff --cached --name-only --diff-filter=ACM
if (-not $StagedFiles) {
    Write-Host "No staged files - skipping checks."
    exit 0
}

# 1. Lint staged files
Write-Host "`n> Running lint checks..."
$lintScript = Join-Path $HooksDir "post-edit-lint.ps1"
if (Test-Path $lintScript) {
    & $lintScript -Files $StagedFiles
    if ($LASTEXITCODE -ne 0) { $CheckErrors++ }
} else {
    Write-Host "  ! post-edit-lint.ps1 not found"
}

# 2. Validate bash scripts
Write-Host "`n> Checking bash scripts..."
$shFiles = $StagedFiles | Where-Object { $_ -match '\.sh$' } | Where-Object { Test-Path $_ }
if ($shFiles) {
    $validateScript = Join-Path $HooksDir "validate-bash.ps1"
    if (Test-Path $validateScript) {
        & $validateScript -Scripts $shFiles
        if ($LASTEXITCODE -ne 0) { $CheckErrors++ }
    } else {
        Write-Host "  ! validate-bash.ps1 not found"
    }
} else {
    Write-Host "  No bash scripts staged."
}

# 3. Check for secrets
Write-Host "`n> Scanning for secrets..."
$SecretsFound = 0
foreach ($f in $StagedFiles) {
    if (-not (Test-Path $f)) { continue }
    if ($f -match '\.(md|txt)$|LICENSE') { continue }

    $content = Get-Content $f -Raw -ErrorAction SilentlyContinue
    if ($content -match '(?i)(password|secret|api_key|token|private_key)\s*[:=]\s*["\x27][^"\x27]{8,}') {
        if ($content -notmatch 'example|template|TODO|CHANGEME|placeholder') {
            Write-Host "  X Possible secret in: $f"
            $SecretsFound++
        }
    }
}

if ($SecretsFound -gt 0) {
    Write-Host "  X Found $SecretsFound file(s) with potential secrets!"
    $CheckErrors++
} else {
    Write-Host "  [OK] No secrets detected."
}

# 4. Check for large files
Write-Host "`n> Checking file sizes..."
$MaxSizeKB = 500
$LargeFiles = 0
foreach ($f in $StagedFiles) {
    if (-not (Test-Path $f)) { continue }
    $sizeKB = [math]::Floor((Get-Item $f).Length / 1024)
    if ($sizeKB -gt $MaxSizeKB) {
        Write-Host "  X $f is ${sizeKB}KB (max: ${MaxSizeKB}KB)"
        $LargeFiles++
    }
}

if ($LargeFiles -gt 0) {
    Write-Host "  X Found $LargeFiles file(s) exceeding ${MaxSizeKB}KB!"
    $CheckErrors++
} else {
    Write-Host "  [OK] All files within size limits."
}

# Summary
Write-Host "`n==================================="
if ($CheckErrors -gt 0) {
    Write-Host "  X FAILED - $CheckErrors check(s) failed"
    Write-Host "  Commit blocked. Fix issues and retry."
    Write-Host "==================================="
    exit 1
} else {
    Write-Host "  [OK] ALL CHECKS PASSED"
    Write-Host "==================================="
    exit 0
}
