# watchdog_15m.ps1 — independent process-termination witness for the 15m server.
#
# 2026-10-31: installed after three silent server exits (no traceback, no WER,
# no faulthandler record).  The watchdog runs OUTSIDE the server's process
# tree (launch it via Win32_Process.Create) and writes its own JSONL record
# to logs/process_watchdog.jsonl — a path no application code writes to.
#
# Captured per target:
#   - inventory at start: PID, parent PID, executable, command line, start
#     time, launch method, watchdog's own PID/PPID;
#   - heartbeat rows every ~60s (process alive, handle held);
#   - termination row: HasExited transition, ExitTime, ExitCode where the
#     OS handle exposes it, plus a WER Application-Error lookup over the
#     preceding window so a hard crash cannot vanish silently again.
#
# Observer only: never signals, restarts, or kills the target.  Single-
# instance enforcement stays inside start_15m.ps1 / the app lifespan guard.

param(
    [Parameter(Mandatory = $true)]
    [int]$TargetPid,

    [int]$PollSeconds = 5,
    [string]$LogPath = "logs\process_watchdog.jsonl",
    [string]$LaunchMethod = "unknown",
    [int]$HeartbeatSeconds = 60
)

$ErrorActionPreference = "Continue"

# Relative log paths resolve against the script directory — WMI/Win32_Create
# spawns this script under System32, not the repo working directory.
if (-not [System.IO.Path]::IsPathRooted($LogPath)) {
    $LogPath = Join-Path $PSScriptRoot $LogPath
}

function Write-WatchdogRow {
    param([hashtable]$Row)
    try {
        $dir = Split-Path -Parent $LogPath
        if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        Add-Content -Path $LogPath -Value ($Row | ConvertTo-Json -Compress -Depth 4)
    } catch {
        # The watchdog must never die because its own log failed; keep going.
    }
}

$now = Get-Date
$watchdogPid = $PID
$watchdogParent = (Get-CimInstance Win32_Process -Filter "ProcessId=$watchdogPid" -ErrorAction SilentlyContinue).ParentProcessId

$proc = Get-Process -Id $TargetPid -ErrorAction SilentlyContinue
$cim = Get-CimInstance Win32_Process -Filter "ProcessId=$TargetPid" -ErrorAction SilentlyContinue

Write-WatchdogRow @{
    event          = "watchdog_start"
    ts_utc         = $now.ToUniversalTime().ToString("o")
    watchdog_pid   = $watchdogPid
    watchdog_ppid  = $watchdogParent
    target_pid     = $TargetPid
    target_ppid    = if ($cim) { $cim.ParentProcessId } else { $null }
    target_exe     = if ($cim) { $cim.ExecutablePath } else { $null }
    target_cmdline = if ($cim) { $cim.CommandLine } else { $null }
    target_start   = if ($cim) { $cim.CreationDate.ToUniversalTime().ToString("o") } else { $null }
    launch_method  = $LaunchMethod
    poll_seconds   = $PollSeconds
}

if ($null -eq $proc) {
    Write-WatchdogRow @{
        event      = "target_missing_at_start"
        ts_utc     = (Get-Date).ToUniversalTime().ToString("o")
        target_pid = $TargetPid
    }
    exit 2
}

$lastHeartbeat = Get-Date
$lastSeenAlive = Get-Date

while ($true) {
    $proc.Refresh()
    if ($proc.HasExited) { break }
    $lastSeenAlive = Get-Date
    if (($lastSeenAlive - $lastHeartbeat).TotalSeconds -ge $HeartbeatSeconds) {
        Write-WatchdogRow @{
            event         = "heartbeat"
            ts_utc        = $lastSeenAlive.ToUniversalTime().ToString("o")
            target_pid    = $TargetPid
            alive         = $true
            working_set_mb = [math]::Round($proc.WorkingSet64 / 1MB, 1)
            cpu_seconds    = $proc.TotalProcessorTime.TotalSeconds
        }
        $lastHeartbeat = $lastSeenAlive
    }
    Start-Sleep -Seconds $PollSeconds
}

$exitTime = $null
$exitCode = $null
try { $exitTime = $proc.ExitTime.ToUniversalTime().ToString("o") } catch {}
try { $exitCode = $proc.ExitCode } catch {}

# Independent crash evidence: WER Application Error events for python in the
# window since the last observed-alive heartbeat (plus a small cushion).
$wer = @()
try {
    $since = $lastSeenAlive.AddMinutes(-2)
    $wer = Get-WinEvent -FilterHashtable @{
        LogName   = "Application"
        Id        = 1000, 1001
        StartTime = $since
    } -MaxEvents 20 -ErrorAction SilentlyContinue |
        Where-Object { $_.Message -match "python" } |
        ForEach-Object {
            @{
                ts_utc    = $_.TimeCreated.ToUniversalTime().ToString("o")
                id        = $_.Id
                provider  = $_.ProviderName
                first_line = ($_.Message -split "`n")[0]
            }
        }
} catch {}

Write-WatchdogRow @{
    event               = "termination"
    ts_utc              = (Get-Date).ToUniversalTime().ToString("o")
    target_pid          = $TargetPid
    last_seen_alive_utc = $lastSeenAlive.ToUniversalTime().ToString("o")
    exit_time_utc       = $exitTime
    exit_code           = $exitCode
    wer_python_events   = $wer
    wer_event_count     = @($wer).Count
}
