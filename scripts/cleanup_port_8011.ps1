#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Kills processes holding port 8011 for MERID server restart.
.DESCRIPTION
    Finds and terminates processes using port 8011 (MERID dev server).
    Use before restarting the server to avoid "address already in use" errors.
.EXAMPLE
    .\scripts\cleanup_port_8011.ps1
#>

param(
    [int]$Port = 8011,
    [switch]$Force = $false
)

Write-Host "Checking for processes using port $Port..." -ForegroundColor Cyan

# Find processes using the port
$connections = netstat -ano | Select-String ":$Port"

if (-not $connections) {
    Write-Host "No processes found using port $Port. Ready to start server." -ForegroundColor Green
    exit 0
}

Write-Host "Found processes using port $Port:" -ForegroundColor Yellow
$connections | ForEach-Object { Write-Host "  $_" }

# Extract PIDs
$pids = $connections | ForEach-Object { 
    ($_ -split '\s+')[-1] 
} | Select-Object -Unique

Write-Host "`nPIDs to terminate: $pids" -ForegroundColor Yellow

if (-not $Force) {
    $confirm = Read-Host "Kill these processes? (y/N)"
    if ($confirm -notin @('y', 'Y', 'yes', 'YES')) {
        Write-Host "Cancelled. Exiting." -ForegroundColor Red
        exit 1
    }
}

# Kill processes
foreach ($pid in $pids) {
    try {
        $process = Get-Process -Id $pid -ErrorAction Stop
        Write-Host "Killing PID $pid ($($process.ProcessName))..." -ForegroundColor Red
        Stop-Process -Id $pid -Force
        Write-Host "  -> Killed successfully" -ForegroundColor Green
    }
    catch {
        Write-Host "  -> Failed to kill PID ${pid}: $_" -ForegroundColor Red
    }
}

# Verify port is free
Start-Sleep -Seconds 1
$stillInUse = netstat -ano | Select-String ":$Port"
if (-not $stillInUse) {
    Write-Host "`nPort $Port is now free. Ready to start server." -ForegroundColor Green
    exit 0
} else {
    Write-Host "`nWARNING: Port $Port still in use by:" -ForegroundColor Red
    $stillInUse | ForEach-Object { Write-Host "  $_" }
    exit 1
}
