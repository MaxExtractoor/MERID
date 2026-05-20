# MERID Detached Startup Script - 24/7 operation immune to IDE terminal closure
#
# Why this exists:
#   When MERID is launched from a Windsurf/VSCode integrated terminal, the child
#   python.exe inherits the IDE's pseudo-console handle. IDE actions that resize,
#   split, reload, or open sibling terminals can send CTRL_CLOSE_EVENT /
#   CTRL_LOGOFF_EVENT to every attached console process. Those events bypass
#   Python's SIGINT/SIGTERM and our lifespan handler, calling Windows'
#   default ExitProcess() ~5s later. This is what was killing 30-min sessions.
#
# This launcher detaches python.exe from the IDE's console using
# Start-Process, which creates the child in its own (hidden) console.
# Combined with the SetConsoleCtrlHandler installed in web/main.py, the
# server is now immune to both IDE-terminal events AND any leftover
# console events on the new console window.
#
# Usage:
#   .\scripts\start_merid_detached.ps1                  # default port 8011
#   .\scripts\start_merid_detached.ps1 -Port 8011       # explicit port
#   .\scripts\start_merid_detached.ps1 -ValidationMode  # validation mode
#
# Operations:
#   * To check it's running:  Get-Process python | where {$_.MainWindowTitle -like '*MERID*'}
#   * To tail logs:           Get-Content C:\Dev\MERID\logs\merid_stdout.log -Wait -Tail 50
#   * To stop:                python C:\Dev\MERID\tools\merid_config.py stop  (or use the signal-file path)

param(
    [int]$Port = 8011,
    [string]$LogLevel = "info",
    [switch]$ValidationMode,
    [switch]$FreshStart,
    [switch]$NoReload
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

Write-Status "MERID Detached Startup (24/7 mode)" "INFO"
Write-Status "Port=$Port LogLevel=$LogLevel ValidationMode=$ValidationMode FreshStart=$FreshStart NoReload=$NoReload" "INFO"

$projectRoot = "C:\Dev\MERID"
$logDir = Join-Path $projectRoot "logs"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

# Pre-flight: port cleanup so a stale instance doesn't refuse the bind.
$cleanupScript = Join-Path $projectRoot "scripts\preflight_port_cleanup.ps1"
if (Test-Path $cleanupScript) {
    Write-Status "Running pre-flight port cleanup..." "INFO"
    & $cleanupScript -Port $Port -Force
    if ($LASTEXITCODE -ne 0) {
        Write-Status "Port cleanup failed - aborting" "ERROR"
        exit 1
    }
} else {
    Write-Status "Port cleanup script not found at $cleanupScript - continuing" "WARN"
}

# Persist environment variables for the detached process via [Environment]::SetEnvironmentVariable
# (process-scope: only this PowerShell + children inherit). Start-Process inherits.
$env:MERID_ENV = "production"
$env:MERID_LOG_LEVEL = $LogLevel
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"
if ($ValidationMode) { $env:MERID_VALIDATION_MODE = "1" } else { $env:MERID_VALIDATION_MODE = "0" }
if ($FreshStart)     { $env:MERID_FRESH_START = "1" }     else { $env:MERID_FRESH_START = "0" }

# Build uvicorn argument list. Skip --reload-dir flags when -NoReload is set
# (recommended for 24/7 because the reloader spawns a child watcher that gets
# its own console and complicates the SetConsoleCtrlHandler story).
$uvicornArgs = @(
    "-m", "uvicorn", "web.main:app",
    "--host", "0.0.0.0",
    "--port", "$Port",
    "--log-level", $LogLevel,
    "--use-colors"
)
if (-not $NoReload) {
    $uvicornArgs += @("--reload-dir", "merid", "--reload-dir", "web")
}

$stdoutLog = Join-Path $logDir "merid_stdout.log"
$stderrLog = Join-Path $logDir "merid_stderr.log"

Write-Status "Launching detached python.exe (own hidden console)..." "INFO"
Write-Status "stdout -> $stdoutLog" "INFO"
Write-Status "stderr -> $stderrLog" "INFO"

# Start-Process with -WindowStyle Hidden creates the child in a NEW console
# that is NOT shared with the IDE terminal. The child inherits no console
# handle from the IDE, so closing/resizing the IDE terminal cannot deliver
# CTRL_CLOSE_EVENT to the python process.
$proc = Start-Process `
    -FilePath "python" `
    -ArgumentList $uvicornArgs `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -PassThru

if ($null -eq $proc) {
    Write-Status "Failed to start python.exe" "ERROR"
    exit 1
}

Write-Status "MERID launched as PID $($proc.Id) - detached from this terminal" "OK"
Write-Status "Tail logs:  Get-Content $stdoutLog -Wait -Tail 50" "INFO"
Write-Status "Health URL: http://localhost:$Port/api/v1/health" "INFO"
Write-Status "Stop:       Stop-Process -Id $($proc.Id)" "INFO"

# Brief wait so we can detect immediate startup failures (bad import etc.)
Start-Sleep -Seconds 3
$proc.Refresh()
if ($proc.HasExited) {
    Write-Status "python.exe exited within 3s (exit code $($proc.ExitCode)) - check $stderrLog" "ERROR"
    if (Test-Path $stderrLog) {
        Write-Host "--- stderr tail ---" -ForegroundColor Red
        Get-Content $stderrLog -Tail 40
    }
    exit 1
}

Write-Status "Process still running after 3s - startup looks healthy" "OK"
exit 0
