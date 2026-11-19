# Tail the newest server_console err.log for trade-relevant events.
# Writes matching lines to _monitor_hits.txt (appended) and echoes progress.
param(
    [int]$PollSeconds = 15,
    [int]$MaxMinutes = 180
)
$logDir = "C:\Dev\MERID\logs"
$errLog = Get-ChildItem $logDir -Filter 'server_console_*.err.log' |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
$outFile = "C:\Dev\MERID\_monitor_hits.txt"
"monitor start $(Get-Date -Format o) log=$($errLog.Name)" | Out-File $outFile -Encoding utf8

$pattern = 'LIVE-RUNTIME-STATE-TRANSITION|live_entries_enabled|live_startup_preflight|ORDER-INTENT-CREATED|CANONICAL-ORDER-INTENT-PASS|EXEC-PATH|ORDER-SUBMIT|order_submitted|SUBMITTED|ORDER-ACK|order_ack|FILL|apply_fill|ORDER-LIFECYCLE|ROUTER-REJECTED|STALE-DECISION|ENTRY-IDEMPOTENCY|circuit_breaker|CIRCUIT-BREAKER|reconcil|RECONCILE-HALT|entry_halted|ENTRY-HALT|HEARTBEAT|Traceback|CRITICAL|uvicorn.error|Application startup|positions=|FILL-INGEST|ORDER-PLACE|trading_shard|SHARD|insufficient'

$deadline = (Get-Date).AddMinutes($MaxMinutes)
$offset = 0

while ((Get-Date) -lt $deadline) {
    try {
        $fi = Get-Item $errLog.FullName
        if ($fi.Length -lt $offset) { $offset = 0 }  # rotated/truncated
        if ($fi.Length -gt $offset) {
            $fs = [System.IO.File]::Open($errLog.FullName, 'Open', 'Read', 'ReadWrite')
            $fs.Seek($offset, 'Begin') | Out-Null
            $sr = New-Object System.IO.StreamReader($fs)
            $chunk = $sr.ReadToEnd()
            $sr.Close(); $fs.Close()
            $offset = $fi.Length
            $hits = ($chunk -split "`n") | Where-Object { $_ -match $pattern }
            if ($hits) {
                $stamp = Get-Date -Format 'HH:mm:ss'
                foreach ($h in $hits) {
                    $line = "$stamp | " + $h.Substring(0, [Math]::Min(500, $h.Length))
                    Add-Content -Path $outFile -Value $line -Encoding utf8
                }
            }
        }
    } catch {
        Add-Content -Path $outFile -Value "$(Get-Date -Format 'HH:mm:ss') | MONITOR-ERROR: $_" -Encoding utf8
    }
    Start-Sleep -Seconds $PollSeconds
}
"monitor end $(Get-Date -Format o)" | Out-File $outFile -Append -Encoding utf8
