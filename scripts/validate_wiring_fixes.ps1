#!/usr/bin/env pwsh
# Validation script for Deep Wiring Audit fixes
# Thin wrapper around Python CI validation for local/dev use

param(
    [switch]$CheckDiffs,
    [string]$BaseRef = ""
)

$ErrorActionPreference = "Stop"

Write-Host "=== MERID Wiring Fixes Validation ===" -ForegroundColor Cyan
Write-Host "Delegating to Python validation script..." -ForegroundColor Gray
Write-Host ""

# Build Python command
$pythonCmd = "python scripts/validate_wiring_ci.py"
if ($CheckDiffs) {
    $pythonCmd += " --check-diffs"
    if ($BaseRef) {
        $pythonCmd += " --base-ref $BaseRef"
    }
}

# Run Python validation
Invoke-Expression $pythonCmd

exit $LASTEXITCODE
