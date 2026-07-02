# MERID Production Startup Script with Pre-flight Checks
# Usage: .\scripts\start_merid.ps1 [-Port 8011] [-LogLevel info] [-ValidationMode]

param(
    [int]$Port = 8011,
    [string]$LogLevel = "info",
    [switch]$ValidationMode,
    [switch]$FreshStart,
    [switch]$SkipPortCleanup
)

$ErrorActionPreference = "Stop"

function Write-Status {
    param([string]$Message, [string]$Status = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    switch ($Status) {
        "OK"    { Write-Host "[$timestamp] $Message" -ForegroundColor Green }
        "WARN"  { Write-Host "[$timestamp] $Message" -ForegroundColor Yellow }
        "ERROR" { Write-Host "[$timestamp] $Message" -ForegroundColor Red }
        "INFO"  { Write-Host "[$timestamp] $Message" -ForegroundColor Cyan }
    }
}

# ═══════════════════════════════════════════════════════════════════════════════
# PRE-FLIGHT CHECKS
# ═══════════════════════════════════════════════════════════════════════════════

Write-Status "MERID Startup Sequence Initiated" "INFO"
Write-Status "Configuration: Port=$Port, LogLevel=$LogLevel, ValidationMode=$ValidationMode, FreshStart=$FreshStart" "INFO"

# 1. Port cleanup (unless skipped)
if (-not $SkipPortCleanup) {
    Write-Status "Running pre-flight port cleanup..." "INFO"
    $cleanupScript = Join-Path $PSScriptRoot "preflight_port_cleanup.ps1"
    if (Test-Path $cleanupScript) {
        & $cleanupScript -Port $Port -Force
        if ($LASTEXITCODE -ne 0) {
            Write-Status "Port cleanup failed - aborting startup" "ERROR"
            exit 1
        }
    } else {
        Write-Status "Port cleanup script not found at $cleanupScript" "WARN"
    }
} else {
    Write-Status "Port cleanup skipped (requested)" "WARN"
}

# 2. Environment validation
Write-Status "Validating environment..." "INFO"

$requiredEnvVars = @(
    "KALSHI_API_KEY_ID",
    "KALSHI_PRIVATE_KEY_PATH"
)

$missingEnvVars = @()
foreach ($var in $requiredEnvVars) {
    if (-not [Environment]::GetEnvironmentVariable($var)) {
        $missingEnvVars += $var
    }
}

if ($missingEnvVars.Count -gt 0) {
    Write-Status "Missing required environment variables: $($missingEnvVars -join ', ')" "ERROR"
    Write-Status "Please configure your .env file or environment before starting." "ERROR"
    exit 1
}

# 3. Check Python and dependencies
Write-Status "Checking Python environment..." "INFO"
try {
    $pythonVersion = python --version 2>&1
    Write-Status "Python version: $pythonVersion" "OK"
} catch {
    Write-Status "Python not found in PATH" "ERROR"
    exit 1
}

# Check if uvicorn is available
try {
    $uvicornVersion = python -c "import uvicorn; print(uvicorn.__version__)" 2>$null
    if ($uvicornVersion) {
        Write-Status "Uvicorn version: $uvicornVersion" "OK"
    }
} catch {
    Write-Status "Uvicorn not installed - run: pip install uvicorn[standard]" "ERROR"
    exit 1
}

# 4. Data directory check
$dataDir = "C:\Dev\MERID\data"
if (-not (Test-Path $dataDir)) {
    Write-Status "Creating data directory: $dataDir" "INFO"
    New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
}

# ═══════════════════════════════════════════════════════════════════════════════
# STARTUP
# ═══════════════════════════════════════════════════════════════════════════════

Write-Status "All pre-flight checks passed - starting MERID..." "OK"
Write-Status "Starting uvicorn on port $Port..." "INFO"

# Build environment variables
$env:MERID_ENV = "production"
$env:MERID_LOG_LEVEL = $LogLevel

if ($ValidationMode) {
    $env:MERID_VALIDATION_MODE = "1"
    Write-Status "VALIDATION MODE enabled - startup will be faster (services deferred)" "WARN"
} else {
    $env:MERID_VALIDATION_MODE = "0"
}

if ($FreshStart) {
    $env:MERID_FRESH_START = "1"
    Write-Status "FRESH START enabled - all transient state will be reset" "WARN"
} else {
    $env:MERID_FRESH_START = "0"
}

# Set Windows-specific optimizations
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"

# Change to project root
$projectRoot = "C:\Dev\MERID"
Set-Location $projectRoot

Write-Status "Launching uvicorn..." "INFO"
Write-Status "══════════════════════════════════════════════════════════════════" "INFO"
Write-Status "MERID will be available at: http://localhost:$Port" "INFO"
Write-Status "Health check: http://localhost:$Port/api/v1/health" "INFO"
Write-Status "Press Ctrl+C to stop" "INFO"
Write-Status "══════════════════════════════════════════════════════════════════" "INFO"

# Start uvicorn with all output going to console
try {
    python -m uvicorn web.main_15m_lean:app `
        --host 0.0.0.0 `
        --port $Port `
        --log-level $LogLevel `
        --reload-dir merid `
        --reload-dir web `
        --use-colors
} catch {
    Write-Status "MERID exited with error: $_" "ERROR"
    exit 1
}
