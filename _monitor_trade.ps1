# Monitor for order attempts / submissions / fills (pid 13848 run).
$errLog = "logs\server_console_20261104_095622.err.log"
$lastSize = 0
if (Test-Path $errLog) { $lastSize = (Get-Item $errLog).Length }
for ($i = 0; $i -lt 240; $i++) {
    $attempts = & .\.venv\Scripts\python.exe _attempt_count.py 2>$null
    $newLines = ""
    if (Test-Path $errLog) {
        $size = (Get-Item $errLog).Length
        if ($size -gt $lastSize) {
            $fs = [System.IO.File]::Open($errLog, 'Open', 'Read', 'ReadWrite')
            $fs.Seek($lastSize, 'Begin') | Out-Null
            $sr = New-Object System.IO.StreamReader($fs)
            $chunk = $sr.ReadToEnd()
            $sr.Close(); $fs.Close()
            $hits = ($chunk -split "`n") | Where-Object { $_ -match "ORDER_SUBMIT|SUBMITTED|FILLED|order_ack|pinned_fav|ORDER-ACK|FILL-INGEST|apply_fill|ORDER-PLACE|route_result|SEQUENCE-GAP|DELTA-DROP" } | Select-Object -First 8
            if ($hits) { $newLines = ($hits -join "`n") }
        }
        $lastSize = $size
    }
    $ts = Get-Date -Format "HH:mm:ss"
    Write-Host "[$ts] attempts_this_run=$attempts"
    if ($newLines) { Write-Host ($newLines.Substring(0, [Math]::Min(2000, $newLines.Length))) }
    Start-Sleep -Seconds 30
}
