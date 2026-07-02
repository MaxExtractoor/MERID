#!/usr/bin/env powershell
# 15m Architecture Validator

param(
    [switch]$Verbose
)

$ErrorActionPreference = "Stop"

Write-Host "15m Architecture Validator" -ForegroundColor Cyan
Write-Host "====================" -ForegroundColor Cyan
Write-Host ""

# Test 1: Static Architectural Separation
Write-Host "Testing static architectural separation..." -ForegroundColor Yellow
try {
    Push-Location "C:\Dev\MERID"
    $result = py -m pytest tests/test_15m_architectural_separation.py -v --tb=no 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "PASS: Static architectural separation tests" -ForegroundColor Green
    } else {
        Write-Host "FAIL: Static architectural separation tests" -ForegroundColor Red
        exit 1
    }
}
catch {
    Write-Host "FAIL: Failed to run static tests: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    Pop-Location
}

# Test 2: Runtime Readiness
Write-Host "Testing runtime readiness..." -ForegroundColor Yellow
try {
    Push-Location "C:\Dev\MERID"
    $result = py -m pytest tests/test_15m_runtime_readiness.py -v --tb=no 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "PASS: Runtime readiness tests" -ForegroundColor Green
    } else {
        Write-Host "FAIL: Runtime readiness tests" -ForegroundColor Red
        exit 1
    }
}
catch {
    Write-Host "FAIL: Failed to run runtime tests: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    Pop-Location
}

# Test 3: Server Health Check
Write-Host "Testing server health..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "http://localhost:8011/api/v1/health" -TimeoutSec 5
    if ($response.status -eq "ok" -or $response.status -eq "initializing") {
        Write-Host "PASS: Server health check" -ForegroundColor Green
    } else {
        Write-Host "FAIL: Server health check: $($response.status)" -ForegroundColor Red
        exit 1
    }
}
catch {
    Write-Host "FAIL: Server health check: Server not responding" -ForegroundColor Red
    Write-Host "Make sure the 15m stack is running: .\start_15m.ps1" -ForegroundColor Yellow
    exit 1
}

# Test 4: System Health Check
Write-Host "Testing system health..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "http://localhost:8011/api/v1/system/health" -TimeoutSec 5
    $agentGridStatus = $response.services.agent_grid.status
    
    if ($agentGridStatus -in @("healthy", "running", "initialized", "degraded")) {
        Write-Host "PASS: System health check (agent_grid: $agentGridStatus)" -ForegroundColor Green
    } else {
        Write-Host "FAIL: System health check: agent_grid status is $agentGridStatus" -ForegroundColor Red
        exit 1
    }
}
catch {
    Write-Host "FAIL: System health check: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# Test 5: Agent Grid Check
Write-Host "Testing agent grid..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "http://localhost:8011/api/v1/agents" -TimeoutSec 5
    if ($response.initialized -and $response.reason -ne "agent_grid_missing") {
        Write-Host "PASS: Agent grid check ($($response.summary.total) agents)" -ForegroundColor Green
    } else {
        Write-Host "FAIL: Agent grid check: $($response.reason)" -ForegroundColor Red
        exit 1
    }
}
catch {
    Write-Host "FAIL: Agent grid check: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# Test 6: Legacy Main Quarantine
Write-Host "Testing legacy main quarantine..." -ForegroundColor Yellow
$legacyMain = "C:\Dev\MERID\web\main.py"
$quarantinedMain = "C:\Dev\MERID\web\main_legacy.py"

if (Test-Path $legacyMain) {
    Write-Host "FAIL: Legacy main quarantine: main.py still exists" -ForegroundColor Red
    exit 1
}
elseif (-not (Test-Path $quarantinedMain)) {
    Write-Host "FAIL: Legacy main quarantine: main_legacy.py not found" -ForegroundColor Red
    exit 1
}
else {
    Write-Host "PASS: Legacy main quarantine" -ForegroundColor Green
}

# Summary
Write-Host ""
Write-Host "ALL VALIDATIONS PASSED!" -ForegroundColor Green
Write-Host "15m stack is architecturally sound and ready for trading" -ForegroundColor Green
Write-Host ""
Write-Host "Validation Summary:" -ForegroundColor Cyan
Write-Host "  PASS: Static architectural separation tests" -ForegroundColor Green
Write-Host "  PASS: Runtime readiness tests" -ForegroundColor Green
Write-Host "  PASS: Server health check" -ForegroundColor Green
Write-Host "  PASS: System health check" -ForegroundColor Green
Write-Host "  PASS: Agent grid check" -ForegroundColor Green
Write-Host "  PASS: Legacy main quarantine" -ForegroundColor Green
Write-Host ""
Write-Host "Ready for production trading!" -ForegroundColor Green

exit 0
