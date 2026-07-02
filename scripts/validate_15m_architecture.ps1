#!/usr/bin/env powershell
# 15m Architecture Alignment Validator
# This script validates that the 15m stack maintains architectural separation
# and enforces the new invariants established in Pass 1-5

param(
    [switch]$Verbose,
    [switch]$Fix,
    [string]$ServerHost = "localhost",
    [int]$ServerPort = 8011
)

$ErrorActionPreference = "Stop"

Write-Host "🔍 15m Architecture Alignment Validator" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""

# Configuration
$BaseUrl = "http://${ServerHost}:${ServerPort}"
$CriticalEndpoints = @(
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

$HardFailurePatterns = @(
    "No module named 'merid.prediction.agent_grid'",
    "agent_grid_missing",
    "import.*error",
    "ImportError"
)

function Write-ValidationResult {
    param(
        [string]$Test,
        [bool]$Passed,
        [string]$Message,
        [string]$Details = ""
    )
    
    $Status = if ($Passed) { "✅ PASS" } else { "❌ FAIL" }
    $Color = if ($Passed) { "Green" } else { "Red" }
    
    Write-Host "$Status - $Test" -ForegroundColor $Color
    if ($Message) {
        Write-Host "    $Message" -ForegroundColor $Color
    }
    if ($Details -and $Verbose) {
        Write-Host "    $Details" -ForegroundColor Gray
    }
    Write-Host ""
}

function Test-ServerAvailability {
    try {
        $response = Invoke-RestMethod -Uri "$BaseUrl/api/v1/health" -TimeoutSec 5
        return $true
    }
    catch {
        return $false
    }
}

function Test-CriticalEndpoints {
    $failedEndpoints = @()
    
    foreach ($endpoint in $CriticalEndpoints) {
        try {
            $response = Invoke-RestMethod -Uri "$BaseUrl$endpoint" -TimeoutSec 10
            if ($response.status -eq "ok" -or $response.status -eq "healthy" -or $response.ContainsKey("schema_version")) {
                Write-ValidationResult -Test "Endpoint $endpoint" -Passed $true -Message "Accessible"
            }
            else {
                $failedEndpoints += $endpoint
                Write-ValidationResult -Test "Endpoint $endpoint" -Passed $false -Message "Unhealthy status: $($response.status)"
            }
        }
        catch {
            $failedEndpoints += $endpoint
            Write-ValidationResult -Test "Endpoint $endpoint" -Passed $false -Message "Error: $($_.Exception.Message)"
        }
    }
    
    return $failedEndpoints.Count -eq 0
}

function Test-ImportErrors {
    try {
        $response = Invoke-RestMethod -Uri "$BaseUrl/api/v1/system/health" -TimeoutSec 10
        
        # Check for import errors in agent_grid service
        if ($response.services.agent_grid.error) {
            $error = $response.services.agent_grid.error
            foreach ($pattern in $HardFailurePatterns) {
                if ($error -match $pattern) {
                    Write-ValidationResult -Test "Import Errors" -Passed $false -Message "Found import error: $error"
                    return $false
                }
            }
        }
        
        Write-ValidationResult -Test "Import Errors" -Passed $true -Message "No import errors detected"
        return $true
    }
    catch {
        Write-ValidationResult -Test "Import Errors" -Passed $false -Message "Failed to check system health: $($_.Exception.Message)"
        return $false
    }
}

function Test-AgentGridInitialization {
    try {
        $response = Invoke-RestMethod -Uri "$BaseUrl/api/v1/agents" -TimeoutSec 10
        
        if ($response.initialized -and $response.reason -ne "agent_grid_missing") {
            Write-ValidationResult -Test "Agent Grid Initialization" -Passed $true -Message "Grid initialized with $($response.summary.total) agents"
            return $true
        }
        else {
            Write-ValidationResult -Test "Agent Grid Initialization" -Passed $false -Message "Grid not initialized: $($response.reason)"
            return $false
        }
    }
    catch {
        Write-ValidationResult -Test "Agent Grid Initialization" -Passed $false -Message "Failed to check agents: $($_.Exception.Message)"
        return $false
    }
}

function Test-ArchitecturalSeparation {
    $repoRoot = Split-Path -Parent $PSScriptRoot
    $webDir = Join-Path $repoRoot "web"
    
    # Check for legacy main.py
    $legacyMain = Join-Path $webDir "main.py"
    $quarantinedMain = Join-Path $webDir "main_legacy.py"
    
    if (Test-Path $legacyMain) {
        Write-ValidationResult -Test "Legacy Main Quarantine" -Passed $false -Message "Legacy main.py still exists"
        return $false
    }
    elseif (-not (Test-Path $quarantinedMain)) {
        Write-ValidationResult -Test "Legacy Main Quarantine" -Passed $false -Message "Quarantined main_legacy.py not found"
        return $false
    }
    else {
        Write-ValidationResult -Test "Legacy Main Quarantine" -Passed $true -Message "Legacy main.py properly quarantined"
    }
    
    # Check startup scripts
    $startupScripts = @(
        "start_15m.ps1",
        "start_kalshi_15m.ps1"
    )
    
    foreach ($script in $startupScripts) {
        $scriptPath = Join-Path $repoRoot $script
        if (Test-Path $scriptPath) {
            $content = Get-Content $scriptPath -Raw
            if ($content -match "web\.main_15m_lean:app") {
                Write-ValidationResult -Test "Startup Script $script" -Passed $true -Message "Uses correct 15m entrypoint"
            }
            elseif ($content -match "web\.main:app") {
                Write-ValidationResult -Test "Startup Script $script" -Passed $false -Message "Uses legacy entrypoint"
                return $false
            }
            else {
                Write-ValidationResult -Test "Startup Script $script" -Passed $true -Message "No hardcoded entrypoint found"
            }
        }
    }
    
    return $true
}

function Test-StaticGuardrails {
    $repoRoot = Split-Path -Parent $PSScriptRoot
    $testFile = Join-Path $repoRoot "tests\test_15m_architectural_separation.py"
    
    if (-not (Test-Path $testFile)) {
        Write-ValidationResult -Test "Static Guardrails" -Passed $false -Message "test_15m_architectural_separation.py not found"
        return $false
    }
    
    # Try to run the static test
    try {
        Push-Location $repoRoot
        $result = python -m pytest tests/test_15m_architectural_separation.py -v --tb=no 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-ValidationResult -Test "Static Guardrails" -Passed $true -Message "All architectural separation tests pass"
            return $true
        }
        else {
            Write-ValidationResult -Test "Static Guardrails" -Passed $false -Message "Architectural separation tests failed"
            return $false
        }
    }
    catch {
        Write-ValidationResult -Test "Static Guardrails" -Passed $false -Message "Failed to run static tests: $($_.Exception.Message)"
        return $false
    }
    finally {
        Pop-Location
    }
}

function Test-RuntimeReadiness {
    $repoRoot = Split-Path -Parent $PSScriptRoot
    $testFile = Join-Path $repoRoot "tests\test_15m_runtime_readiness.py"
    
    if (-not (Test-Path $testFile)) {
        Write-ValidationResult -Test "Runtime Readiness" -Passed $false -Message "test_15m_runtime_readiness.py not found"
        return $false
    }
    
    # Try to run the runtime test
    try {
        Push-Location $repoRoot
        $result = python -m pytest tests/test_15m_runtime_readiness.py -v --tb=no 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-ValidationResult -Test "Runtime Readiness" -Passed $true -Message "All runtime readiness tests pass"
            return $true
        }
        else {
            Write-ValidationResult -Test "Runtime Readiness" -Passed $false -Message "Runtime readiness tests failed"
            return $false
        }
    }
    catch {
        Write-ValidationResult -Test "Runtime Readiness" -Passed $false -Message "Failed to run runtime tests: $($_.Exception.Message)"
        return $false
    }
    finally {
        Pop-Location
    }
}

# Main validation logic
Write-Host "🔧 Validating 15m stack at $BaseUrl" -ForegroundColor Yellow
Write-Host ""

# Check if server is available
if (-not (Test-ServerAvailability)) {
    Write-ValidationResult -Test "Server Availability" -Passed $false -Message "Server not responding at $BaseUrl"
    Write-Host "💡 Make sure the 15m stack is running: .\start_15m.ps1" -ForegroundColor Yellow
    exit 1
}

Write-ValidationResult -Test "Server Availability" -Passed $true -Message "Server responding"

# Run all validation tests
$tests = @(
    { Test-CriticalEndpoints },
    { Test-ImportErrors },
    { Test-AgentGridInitialization },
    { Test-ArchitecturalSeparation },
    { Test-StaticGuardrails },
    { Test-RuntimeReadiness }
)

$passedTests = 0
$totalTests = $tests.Count

foreach ($test in $tests) {
    if (& $test) {
        $passedTests++
    }
}

# Summary
Write-Host "📊 VALIDATION SUMMARY" -ForegroundColor Cyan
Write-Host "===================" -ForegroundColor Cyan
Write-Host "Passed: $passedTests/$totalTests tests" -ForegroundColor $(if ($passedTests -eq $totalTests) { "Green" } else { "Yellow" })

if ($passedTests -eq $totalTests) {
    Write-Host "🎉 ALL VALIDATIONS PASSED!" -ForegroundColor Green
    Write-Host "✅ 15m stack is architecturally sound and ready for trading" -ForegroundColor Green
    exit 0
}
else {
    Write-Host "⚠️  SOME VALIDATIONS FAILED" -ForegroundColor Yellow
    Write-Host "❌ 15m stack has architectural issues that need attention" -ForegroundColor Red
    Write-Host ""
    Write-Host "🔧 To fix issues:" -ForegroundColor Yellow
    Write-Host "1. Review failed tests above" -ForegroundColor Yellow
    Write-Host "2. Fix architectural violations" -ForegroundColor Yellow
    Write-Host "3. Re-run validator: .\scripts\validate_15m_architecture.ps1" -ForegroundColor Yellow
    exit 1
