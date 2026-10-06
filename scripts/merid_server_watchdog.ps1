# MERID 15m server watchdog — detached supervisor.
#
# Liveness contract (2026-10-06 rewrite):
#   - "up" requires BOTH the port listening AND the loop healthy
#     (/api/v1/loop-status: running=true, status=running, fresh heartbeat).
#     A hung process that still owns the port is a failure — the previous
#     version only checked the port and sat through a ~2h dead loop window.
#   - Before relaunching, kill every process whose command line matches the
#     server (main_15m_lean / start_15m.ps1) — never leave two instances.
#   - Relaunch goes through start_15m.ps1 so startup preflight still gates
#     live entries; the watchdog restores liveness only.
#   - Every state change is appended to logs\watchdog.log with the cause.
#
# Launch via scripts\_launch_watchdog.ps1 (WMI-detached).

$RepoRoot      = "C:\Dev\MERID"
$LogFile       = Join-Path $RepoRoot "logs\watchdog.log"
$Port          = 8011
$PollSeconds   = 20
$FailThreshold = 3
$RelaunchGraceSeconds = 120
$MinRelaunchGapSeconds = 300
# Loop heartbeat older than this while the port is listening = hung.
$HangThresholdSeconds = 240
# A server process younger than this is still booting — don't count as down.
$BootGraceSeconds = 180

function Log($msg) {
    $line = "{0} | watchdog_pid={1} | {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $PID, $msg
    try { Add-Content -Path $LogFile -Value $line } catch {}
}

function Get-ServerProcesses {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'main_15m_lean|start_15m\.ps1' }
}

function Test-LoopHealthy {
    # Returns $true only when the port is listening AND the loop reports
    # itself running with a fresh heartbeat.  A bound port alone is not
    # proof of life — a wedged event loop still owns the socket.
    $listening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $listening) { return $false }
    try {
        $st = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/loop-status" -TimeoutSec 8
    } catch {
        Log "loop-status probe failed: $($_.Exception.Message)"
        return $false
    }
    if ($st.running -ne $true -or $st.status -ne 'running') {
        # 'starting' is honest boot state, not a failure.
        if ($st.status -eq 'starting') { return $true }
        Log "loop-status reports status=$($st.status) running=$($st.running)"
        return $false
    }
    $hb = $st.heartbeat_age_seconds
    if ($null -ne $hb) {
        if ([double]$hb -gt $HangThresholdSeconds) {
            Log "loop heartbeat stale: ${hb}s > ${HangThresholdSeconds}s"
            return $false
        }
        return $true
    }
    if ($st.last_cycle_ts) {
        try {
            $cycleAge = ((Get-Date).ToUniversalTime() - [datetimeoffset]::Parse($st.last_cycle_ts).UtcDateTime).TotalSeconds
            if ($cycleAge -gt $HangThresholdSeconds) {
                Log "last_cycle_ts stale: $([int]$cycleAge)s > ${HangThresholdSeconds}s"
                return $false
            }
            return $true
        } catch {
            Log "last_cycle_ts parse failed: $($st.last_cycle_ts)"
            return $false
        }
    }
    # running=true, status=running, but no heartbeat fields at all:
    # accept (older builds), the port check already proved the listener.
    return $true
}

function Stop-ServerProcesses($reason) {
    $procs = @(Get-ServerProcesses)
    foreach ($p in $procs) {
        Log "killing server process pid=$($p.ProcessId) ($reason)"
        try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop } catch {
            Log "Stop-Process pid=$($p.ProcessId) failed: $($_.Exception.Message)"
        }
    }
    return $procs.Count
}

Log "watchdog started; monitoring port $Port (health=loop-status, hang>${HangThresholdSeconds}s)"
$fails = 0
$lastRelaunch = [DateTime]::MinValue

while ($true) {
    $healthy = Test-LoopHealthy
    if ($healthy) {
        if ($fails -ge $FailThreshold) { Log "server recovered on port $Port" }
        $fails = 0
    } else {
        # Do not penalize a server that is still booting: a matching process
        # younger than the boot grace window is mid-startup, not hung.
        $booting = @(Get-ServerProcesses) | Where-Object {
            try {
                ((Get-Date) - [Management.ManagementDateTimeConverter]::ToDateTime($_.CreationDate)).TotalSeconds -lt $BootGraceSeconds
            } catch { $false }
        }
        if ($booting.Count -gt 0) {
            if ($fails -gt 0) { Log "unhealthy but server booting (pid=$($booting[0].ProcessId)); resetting" }
            $fails = 0
        } else {
            $fails++
            if ($fails -eq 1) { Log "server unhealthy or down (check 1/$FailThreshold)" }
            if ($fails -ge $FailThreshold) {
                $gap = (New-TimeSpan -Start $lastRelaunch -End (Get-Date)).TotalSeconds
                if ($gap -lt $MinRelaunchGapSeconds) {
                    Log "server unhealthy but last relaunch $([int]$gap)s ago (< $MinRelaunchGapSeconds); waiting"
                } else {
                    $lastRelaunch = Get-Date
                    $killed = Stop-ServerProcesses "watchdog relaunch after $fails failed health checks"
                    Log "server down/hung for $fails checks (killed $killed stale processes) - relaunching start_15m.ps1"
                    try {
                        $cmd = 'cd /d ' + $RepoRoot + ' && powershell -NoProfile -ExecutionPolicy Bypass -File start_15m.ps1 >> logs\server_console_detached.log 2>&1'
                        $r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
                            CommandLine = 'cmd /c "' + $cmd + '"'
                            CurrentDirectory = $RepoRoot
                        }
                        if ($r.ReturnValue -eq 0) {
                            Log "relaunch spawned via WMI pid=$($r.ProcessId)"
                        } else {
                            Log "WMI relaunch failed: ReturnValue=$($r.ReturnValue)"
                        }
                    } catch {
                        Log "relaunch exception: $($_.Exception.Message)"
                    }
                    Start-Sleep -Seconds $RelaunchGraceSeconds
                    $fails = 0
                }
            }
        }
    }
    Start-Sleep -Seconds $PollSeconds
}
