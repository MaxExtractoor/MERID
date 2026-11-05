# Install/remove the MERID Kalshi book-archiver scheduled task.
#
# Deploys scripts\kalshi_book_archiver.py as an always-on, restart-on-failure
# collector.  IMPORTANT: the action invokes the BASE interpreter (pythonw.exe)
# directly, NOT .venv\Scripts\python.exe — this venv's launcher is a redirector
# that spawns the base interpreter as an untracked child, so stopping the task
# would leave the collector running.  The archiver script self-bootstraps the
# venv's site-packages when launched by a non-venv interpreter.
#
# Usage:
#   powershell -File scripts\install_book_archiver_task.ps1            # install
#   powershell -File scripts\install_book_archiver_task.ps1 -Remove    # remove
param(
    [switch]$Remove,
    [string]$TaskName = "MERID-KalshiBookArchiver",
    [string]$RepoRoot = "C:\Dev\MERID",
    [string]$PythonExe = "C:\Users\Chris\AppData\Local\Programs\Python\Python311\pythonw.exe"
)

$ErrorActionPreference = "Stop"

if ($Remove) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Output "removed task '$TaskName'"
    } else {
        Write-Output "task '$TaskName' not registered"
    }
    return
}

if (-not (Test-Path $PythonExe)) {
    throw "base interpreter not found at $PythonExe"
}
$script = Join-Path $RepoRoot "scripts\kalshi_book_archiver.py"
if (-not (Test-Path $script)) {
    throw "archiver script not found at $script"
}

# Single-process action: tracked pid IS the collector, so Stop-ScheduledTask
# cannot leave descendants.
$action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "`"$script`"" `
    -WorkingDirectory $RepoRoot

# Two triggers:
#  1) AtLogOn of the current interactive user (no stored credentials).
#  2) A 1-minute repeating start attempt, ~indefinitely.  This is the real
#     supervision: Task Scheduler's RestartOnFailure does NOT fire when the
#     process is terminated externally (taskkill, crash), so instead the
#     scheduler tries to start the collector every minute and relies on
#     MultipleInstancesPolicy=IgnoreNew — a live collector makes the attempt
#     a silent no-op; a dead/missing one gets relaunched within 60s.
$triggerLogon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$triggerRepeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 1) `
    -RepetitionDuration (New-TimeSpan -Days 7300)

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 30 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger @($triggerLogon, $triggerRepeat) `
    -Settings $settings `
    -Description "MERID Phase A' raw Kalshi 15m orderbook archive collector (read-only market data; no order endpoints)." `
    -Force | Out-Null

Write-Output "registered '$TaskName': $PythonExe `"$script`" (cwd=$RepoRoot)"
Write-Output "  triggers=AtLogOn($env:USERNAME) + repeat-PT1M  restart=30x1min  instances=IgnoreNew"
Write-Output "  start now with:  Start-ScheduledTask -TaskName '$TaskName'"
