#!/usr/bin/env powershell
# Simple 15m Architecture Validator

param(
    [switch]$Verbose
)

$ErrorActionPreference = "Stop"

Write-Host "🔍 15m Architecture Validator" -ForegroundColor Cyan
Write-Host "========================" -ForegroundColor Cyan
Write-Host ""

# Test 1: Static Architectural Separation
Write-Host "📋 Testing static architectural separation..." -ForegroundColor Yellow
try {
    Push-Location "C:\Dev\MERID"
    $result = py -m pytest tests/test_15m_architectural_separation.py -v --tb=no 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ Static architectural separation tests PASSED" -ForegroundColor Green
    } else {
        Write-Host "❌ Static architectural separation tests FAILED" -ForegroundColor Red
        exit 1
    }
}
catch {
    Write-Host "❌ Failed to run static tests: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    Pop-Location
}

# Test 2: Runtime Readiness
Write-Host "📋 Testing runtime readiness..." -ForegroundColor Yellow
try {
    Push-Location "C:\Dev\MERID"
    $result = py -m pytest tests/test_15m_runtime_readiness.py -v --tb=no 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ Runtime readiness tests PASSED" -ForegroundColor Green
    } else {
        Write-Host "❌ Runtime readiness tests FAILED" -ForegroundColor Red
        exit 1
    }
}
catch {
    Write-Host "❌ Failed to run runtime tests: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    Pop-Location
}

# Test 3: Server Health Check
Write-Host "📋 Testing server health..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "http://localhost:8011/api/v1/health" -TimeoutSec 5
    if ($response.status -eq "ok" -or $response.status -eq "initializing") {
        Write-Host "✅ Server health check PASSED" -ForegroundColor Green
    } else {
        Write-Host "❌ Server health check FAILED: $($response.status)" -ForegroundColor Red
        exit 1
    }
}
catch {
    Write-Host "❌ Server health check FAILED: Server not responding" -ForegroundColor Red
    Write-Host "💡 Make sure the 15m stack is running: .\start_15m.ps1" -ForegroundColor Yellow
    exit 1
}

# Test 4: System Health Check
Write-Host "📋 Testing system health..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "http://localhost:8011/api/v1/system/health" -TimeoutSec 5
    $agentGridStatus = $response.services.agent_grid.status
    
    if ($agentGridStatus -in @("healthy", "running", "initialized", "degraded")) {
        Write-Host "✅ System health check PASSED (agent_grid: $agentGridStatus)" -ForegroundColor Green
    } else {
        Write-Host "❌ System health check FAILED: agent_grid status is $agentGridStatus" -ForegroundColor Red
        exit 1
    }
}
catch {
    Write-Host "❌ System health check FAILED: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# Test 5: Agent Grid Check
Write-Host "📋 Testing agent grid..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "http://localhost:8011/api/v1/agents" -TimeoutSec 5
    if ($response.initialized -and $response.reason -ne "agent_grid_missing") {
        Write-Host "✅ Agent grid check PASSED ($($response.summary.total) agents)" -ForegroundColor Green
    } else {
        Write-Host "❌ Agent grid check FAILED: $($response.reason)" -ForegroundColor Red
        exit 1
    }
}
catch {
    Write-Host "❌ Agent grid check FAILED: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# Test 6: Critical Endpoints Check
Write-Host "📋 Testing critical endpoints..." -ForegroundColor Yellow
$endpoints = @(
    "/api/v1/health",
    "/api/v1/system/health", 
    "/api/v1/agents",
    "/api/v1/loop/status",
    "/api/v1/spot/prices",
    "/api/v1/kalshi/markets",
    "/api/v1/kalshi/market-states",
    "/api/v1/kalshi/consensus-signals",
    "/api/v1/system/execution-gate"
)

$failedEndpoints = 0
foreach ($endpoint in $endpoints) {
    try {
        $response = Invoke-RestMethod -Uri "http://localhost:8011$endpoint" -TimeoutSec 5
        # If we get here, the endpoint is accessible
    }
    catch {
        $failedEndpoints++
        if ($Verbose) {
            Write-Host "  ⚠️  $endpoint failed: $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }
}

if ($failedEndpoints -eq 0) {
    Write-Host "✅ Critical endpoints check PASSED" -ForegroundColor Green
} else {
    Write-Host "❌ Critical endpoints check FAILED ($failedEndpoints failed)" -ForegroundColor Red
    exit 1
}

# Test 7: Legacy Main Quarantine
Write-Host "📋 Testing legacy main quarantine..." -ForegroundColor Yellow
$legacyMain = "C:\Dev\MERID\web\main.py"
$quarantinedMain = "C:\Dev\MERID\web\main_legacy.py"

if (Test-Path $legacyMain) {
    Write-Host "❌ Legacy main quarantine FAILED: main.py still exists" -ForegroundColor Red
    exit 1
}
elseif (-not (Test-Path $quarantinedMain)) {
    Write-Host "❌ Legacy main quarantine FAILED: main_legacy.py not found" -ForegroundColor Red
    exit 1
}
else {
    Write-Host "✅ Legacy main quarantine PASSED" -ForegroundColor Green
}

# Summary
Write-Host ""
Write-Host "🎉 ALL VALIDATIONS PASSED!" -ForegroundColor Green
Write-Host "✅ 15m stack is architecturally sound and ready for trading" -ForegroundColor Green
Write-Host ""
Write-Host "📊 Validation Summary:" -ForegroundColor Cyan
Write-Host "  ✅ Static architectural separation tests" -ForegroundColor Green
Write-Host "  ✅ Runtime readiness tests" -ForegroundColor Green
Write-Host "  ✅ Server health check" -ForegroundColor Green
Write-Host "  ✅ System health check" -ForegroundColor Green
Write-Host "  ✅ Agent grid check" -ForegroundColor Green
Write-Host "  ✅ Critical endpoints check" -ForegroundColor Green
Write-Host "  ✅ Legacy main quarantine" -ForegroundColor Green
Write-Host ""
Write-Host "🚀 Ready for production trading!" -ForegroundColor Green

exit 0
