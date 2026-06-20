#requires -Version 5.1
<#
.SYNOPSIS
    Local validation before push - replaces GitHub Actions CI.

.DESCRIPTION
    Runs the same checks the CI/CD Pipeline used to run, but on the local
    machine. Exits non-zero if any check fails, so you can wire it as a
    git pre-push hook:

        # .git/hooks/pre-push (PowerShell on Windows)
        & "$(git rev-parse --show-toplevel)\scripts\validate_local.ps1"

.NOTES
    Tools you need locally (install once):
      * Python 3.12 with the project venv at .venv/Scripts/python.exe
      * ruff       (pip install ruff)
      * mypy       (pip install mypy structlog pydantic fastapi pydantic-settings)
      * pip-audit  (pip install pip-audit)
      * bandit     (pip install bandit)

.EXAMPLE
    PS> .\scripts\validate_local.ps1
    PS> .\scripts\validate_local.ps1 -Strict
#>
[CmdletBinding()]
param(
    [switch]$Strict
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Error "Python venv not found at $Python. Run: python -m venv .venv && .venv\Scripts\pip install -r requirements.txt"
    exit 2
}

$failures = @()
$skips = @()

function Run-Check {
    param([string]$Name, [scriptblock]$Block)
    Write-Host ("=" * 60)
    Write-Host ">> $Name" -ForegroundColor Cyan
    Write-Host ("=" * 60)
    try {
        & $Block
        if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
            $script:failures += $Name
            Write-Host "[FAIL] $Name (exit $LASTEXITCODE)" -ForegroundColor Red
        } else {
            Write-Host "[OK] $Name passed" -ForegroundColor Green
        }
    } catch {
        $script:failures += $Name
        Write-Host "[FAIL] $Name : $_" -ForegroundColor Red
    }
}

function Skip-Check {
    param([string]$Name, [string]$Reason)
    Write-Host ("=" * 60)
    Write-Host "[SKIP] $Name : $Reason" -ForegroundColor Yellow
    Write-Host ("=" * 60)
    $script:skips += "$Name ($Reason)"
}

# ---- 1. ruff lint ----
$ruffExe = Join-Path $ProjectRoot ".venv\Scripts\ruff.exe"
if (Test-Path $ruffExe) {
    Run-Check "ruff" { & $ruffExe check . }
} elseif (Get-Command ruff -ErrorAction SilentlyContinue) {
    Run-Check "ruff" { ruff check . }
} else {
    Skip-Check "ruff" "not installed (pip install ruff)"
}

# ---- 2. Requirements lock drift ----
Run-Check "lock-drift" {
    & $Python scripts/check_requirements_lock.py requirements.txt requirements.lock
}

# ---- 3. Hardening test suite ----
Run-Check "pytest-hardening" {
    & $Python -m pytest `
        tests/test_jwt_v2.py `
        tests/test_auth_routes_v2_flag.py `
        tests/test_logging_helpers.py `
        tests/test_architecture_size_gate.py `
        tests/test_no_new_silent_swallows.py `
        tests/test_p1_hardening.py `
        tests/test_legacy_verify_token_revokes_v2.py `
        tests/test_metric_naming_gate.py `
        tests/test_log_event_name_convention.py `
        tests/test_jwt_v2_metrics.py `
        tests/test_major_quality_gates.py `
        tests/test_minor_quality_gates.py `
        --no-header -q
}

# ---- 4. mypy delta gate ----
& $Python -c "import mypy" 2>$null
if ($LASTEXITCODE -eq 0) {
    Run-Check "mypy-delta-gate" {
        $report = Join-Path $env:TEMP "mypy-report.txt"
        & $Python -m mypy core api kernel --ignore-missing-imports --show-error-codes > $report 2>&1
        & $Python scripts/check_mypy_baseline.py $report quality/mypy-baseline.json
    }
} else {
    Skip-Check "mypy" "not installed (pip install mypy structlog pydantic fastapi pydantic-settings)"
}

# ---- 5. bandit delta gate ----
& $Python -c "import bandit" 2>$null
if ($LASTEXITCODE -eq 0) {
    Run-Check "bandit-delta-gate" {
        $report = Join-Path $env:TEMP "bandit-report.json"
        & $Python -m bandit -r api core kernel -f json -o $report --exit-zero --skip B101 | Out-Null
        & $Python scripts/check_bandit_baseline.py $report quality/bandit-baseline.json
    }
} else {
    Skip-Check "bandit" "not installed (pip install bandit)"
}

# ---- 6. pip-audit delta gate ----
# Auto-skipped on Windows when the repo path contains non-ASCII chars
# (pip-audit dies with UnicodeDecodeError via pip_api._version.version()
# trying to UTF-8-decode the cp1252-encoded subprocess output of `pip
# --version`). Re-run in WSL or Linux container if needed.
$pathHasNonAscii = ($PSScriptRoot -match "[^\x20-\x7E]")
if ($pathHasNonAscii) {
    Skip-Check "pip-audit" "known Windows bug: repo path contains non-ASCII char. Re-run in WSL or Linux."
} else {
    & $Python -c "import pip_audit" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Run-Check "pip-audit-delta-gate" {
            $report = Join-Path $env:TEMP "audit.json"
            # PS5.1: native command stderr creates ErrorRecords that become terminating errors
            # with $ErrorActionPreference="Stop". Temporarily suppress to let pip-audit run cleanly.
            $prev = $ErrorActionPreference
            $ErrorActionPreference = "SilentlyContinue"
            & $Python -m pip_audit -r requirements.txt --format json --output $report --strict
            $auditExit = $LASTEXITCODE
            $ErrorActionPreference = $prev
            if ($auditExit -ne 0 -and -not (Test-Path $report)) {
                throw "pip-audit failed (exit $auditExit)"
            }
            & $Python scripts/check_pip_audit_baseline.py $report quality/pip-audit-baseline.json
        }
    } else {
        Skip-Check "pip-audit" "not installed (pip install pip-audit)"
    }
}

# ---- 7. Silent-swallow baseline self-check ----
Run-Check "silent-swallow-baseline" {
    & $Python scripts/generate_silent_swallow_baseline.py | Out-Null
    git diff --quiet quality/legacy_silent_swallows.json
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[WARN] silent-swallow baseline drifted - review and commit quality/legacy_silent_swallows.json" -ForegroundColor Yellow
        git diff --stat quality/legacy_silent_swallows.json
        $global:LASTEXITCODE = 0
    }
}

# ---- Summary ----
Write-Host ""
Write-Host ("=" * 60) -ForegroundColor White
Write-Host "VALIDATION SUMMARY" -ForegroundColor White
Write-Host ("=" * 60) -ForegroundColor White

if ($skips.Count -gt 0) {
    Write-Host "Skipped:" -ForegroundColor Yellow
    foreach ($s in $skips) { Write-Host "  - $s" -ForegroundColor Yellow }
}

if ($failures.Count -gt 0) {
    Write-Host ""
    Write-Host "FAILED ($($failures.Count)):" -ForegroundColor Red
    foreach ($f in $failures) { Write-Host "  - $f" -ForegroundColor Red }
    exit 1
}

if ($Strict -and $skips.Count -gt 0) {
    Write-Host ""
    Write-Host "STRICT mode: skipped checks count as failures" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "[OK] All checks passed - safe to push" -ForegroundColor Green
exit 0
