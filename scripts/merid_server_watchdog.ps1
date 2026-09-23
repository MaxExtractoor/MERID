# MERID 15m server watchdog — detached supervisor.
# Polls the server port; if it stops listening for FailThreshold consecutive
# checks, relaunches start_15m.ps1 detached.  Relaunch goes through the normal
# startup path, so the startup state machine and preflight still gate live
# entries — the watchdog only restores process liveness, never bypasses
# preflight.  All events are appended to logs\watchdog.log.

$RepoRoot      = "C:\Dev\MERID"
$LogFile       = Join-Path $RepoRoot "logs\watchdog.log"
$Port          = 8011
$PollSeconds   = 20
$FailThreshold = 3
$RelaunchGraceSeconds = 120
$MinRelaunchGapSeconds = 300

function Log($msg) {
    $line = "{0} | watchdog_pid={1} | {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $PID, $msg
    try { Add-Content -Path $LogFile -Value $line } catch {}
}

Log "watchdog started; monitoring port $Port"
$fails = 0
$lastRelaunch = [DateTime]::MinValue

while ($true) {
    $listening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($listening) {
        if ($fails -ge $FailThreshold) { Log "server recovered on port $Port" }
        $fails = 0
    } else {
        # A server process that is still booting (~2 min) will not yet own the
        # port — do not count that as a failure or we double-launch.
        $booting = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -match 'start_15m\.ps1|main_15m_lean' }
        if ($booting) {
            if ($fails -gt 0) { Log "port $Port not listening but server process alive (pid=$($booting[0].ProcessId)); still booting" }
            $fails = 0
        } else {
            $fails++
        if ($fails -eq 1) { Log "port $Port not listening (check 1/$FailThreshold)" }
        if ($fails -ge $FailThreshold) {
            $gap = (New-TimeSpan -Start $lastRelaunch -End (Get-Date)).TotalSeconds
            if ($gap -lt $MinRelaunchGapSeconds) {
                Log "server down but last relaunch ${gap}s ago (< $MinRelaunchGapSeconds); waiting"
            } else {
                $lastRelaunch = Get-Date
                Log "server down for $fails checks - relaunching start_15m.ps1"
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
    Start-Sleep -Seconds $PollSeconds
}
