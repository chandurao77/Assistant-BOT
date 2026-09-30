# Hook: Post-Edit Lint (PowerShell)
# Runs linters on modified files after each edit to catch issues early.
# Usage: .\hooks\post-edit-lint.ps1 [file1] [file2] ...

param([string[]]$Files)

$ErrorActionPreference = 'Continue'

if (-not $Files) {
    $Files = git diff --name-only --cached 2>$null
}

if (-not $Files) {
    Write-Host "No changed files to lint."
    exit 0
}

$Errors = 0

# -- Python files --
$PyFiles = $Files | Where-Object { $_ -match '\.py$' } | Where-Object { Test-Path $_ }
if ($PyFiles) {
    Write-Host "`u{1F40D} Linting Python files..."

    foreach ($f in $PyFiles) {
        try {
            python -c "import py_compile, sys; py_compile.compile(sys.argv[1], doraise=True)" $f 2>$null
        } catch {
            Write-Host "  X Syntax error: $f"
            $Errors++
        }
    }

    if (Get-Command ruff -ErrorAction SilentlyContinue) {
        ruff check @PyFiles --fix --quiet
        if ($LASTEXITCODE -ne 0) { $Errors++ }
    }

    if (Get-Command black -ErrorAction SilentlyContinue) {
        $null = black --check --quiet @PyFiles 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  ! Format issues detected. Run: black $($PyFiles -join ' ')"
        }
    }
}

# -- TypeScript/JavaScript files --
$TsFiles = $Files | Where-Object { $_ -match '\.(ts|tsx|js|jsx)$' } | Where-Object { Test-Path $_ }
if ($TsFiles) {
    Write-Host "`u{1F4D8} Linting TypeScript/JavaScript files..."

    if ((Get-Command npx -ErrorAction SilentlyContinue) -and (Test-Path "node_modules/.bin/eslint")) {
        npx eslint @TsFiles --fix --quiet 2>$null
        if ($LASTEXITCODE -ne 0) { $Errors++ }
    }

    if (Test-Path "tsconfig.json") {
        npx tsc --noEmit --pretty 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  X TypeScript type errors detected"
            $Errors++
        }
    }
}

# -- YAML files --
$YamlFiles = $Files | Where-Object { $_ -match '\.(ya?ml)$' } | Where-Object { Test-Path $_ }
if ($YamlFiles) {
    Write-Host "`u{1F4CB} Validating YAML files..."
    foreach ($f in $YamlFiles) {
        try {
            python -c "import yaml, sys; yaml.safe_load(open(sys.argv[1]))" $f 2>$null
        } catch {
            Write-Host "  X Invalid YAML: $f"
            $Errors++
        }
    }
}

# -- Summary --
if ($Errors -gt 0) {
    Write-Host "`nX Lint completed with $Errors error(s)"
    exit 1
} else {
    Write-Host "`n[OK] All lint checks passed"
    exit 0
}
