# MERID Pre-flight Port Cleanup Script
# Kills any process holding port 8011 before startup

param(
    [int]$Port = 8011,
    [switch]$Force = $false
)

$ErrorActionPreference = "Stop"

function Write-Status {
    param([string]$Message, [string]$Status = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    switch ($Status) {
        "OK"    { Write-Host "[$timestamp] $Message" -ForegroundColor Green }
        "WARN"  { Write-Host "[$timestamp] $Message" -ForegroundColor Yellow }
        "ERROR" { Write-Host "[$timestamp] $Message" -ForegroundColor Red }
        default { Write-Host "[$timestamp] $Message" }
    }
}

Write-Status "Pre-flight check: Port $Port" "INFO"

# Find processes using the port
$connections = netstat -ano | Select-String ":$Port"

if (-not $connections) {
    Write-Status "Port $Port is free - no cleanup needed" "OK"
    exit 0
}

Write-Status "Found processes on port ${Port}:" "WARN"
$connections | ForEach-Object { Write-Status "  $_" }

# Extract unique PIDs
$pids = $connections | ForEach-Object { 
    ($_ -split '\s+')[-1] 
} | Select-Object -Unique | Where-Object { $_ -match '^\d+$' }

if (-not $pids) {
    Write-Status "No valid PIDs found - assuming port is free" "OK"
    exit 0
}

Write-Status "PIDs to terminate: $($pids -join ', ')" "WARN"

if (-not $Force) {
    $confirm = Read-Host "Kill these processes? (y/N)"
    if ($confirm -notin @('y', 'Y', 'yes', 'YES')) {
        Write-Status "Cleanup cancelled by user" "WARN"
        exit 1
    }
}

$killed = @()
$failed = @()

foreach ($targetPid in $pids) {
    try {
        $process = Get-Process -Id $targetPid -ErrorAction SilentlyContinue
        if ($process) {
            $procName = $process.ProcessName
            Stop-Process -Id $targetPid -Force
            Write-Status "Killed PID $targetPid ($procName)" "OK"
            $killed += $targetPid
        }
    }
    catch {
        Write-Status "Failed to kill PID $targetPid`: $_" "ERROR"
        $failed += $targetPid
    }
}

# Verify port is now free
Start-Sleep -Milliseconds 500
$verify = netstat -ano | Select-String ":$Port"

if ($verify) {
    Write-Status "Port $Port still in use after cleanup!" "ERROR"
    Write-Status "Remaining connections:" "ERROR"
    $verify | ForEach-Object { Write-Status "  $_" }
    exit 1
}

Write-Status "Port $Port cleanup complete - killed $($killed.Count) process(es)" "OK"
exit 0
