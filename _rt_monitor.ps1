# Real-time trade monitor: API state + order_decisions.jsonl + decision telemetry.
# Appends one status block per interval to _rt_monitor.txt
$outFile = "C:\Dev\MERID\_rt_monitor.txt"
$deadline = (Get-Date).AddMinutes(180)
$orderFile = "C:\Dev\MERID\logs\order_decisions.jsonl"
$teleFile = "C:\Dev\MERID\logs\decision_telemetry.jsonl"
$orderOffset = (Get-Item $orderFile).Length
$teleOffset = (Get-Item $teleFile).Length
"rt-monitor start $(Get-Date -Format o)" | Out-File $outFile -Encoding utf8

function Read-New($path, [ref]$offset) {
    try {
        $fi = Get-Item $path
        if ($fi.Length -lt $offset.Value) { $offset.Value = 0 }
        if ($fi.Length -le $offset.Value) { return $null }
        $fs = [System.IO.File]::Open($path, 'Open', 'Read', 'ReadWrite')
        $fs.Seek($offset.Value, 'Begin') | Out-Null
        $sr = New-Object System.IO.StreamReader($fs)
        $chunk = $sr.ReadToEnd()
        $sr.Close(); $fs.Close()
        $offset.Value = $fi.Length
        return $chunk
    } catch { return $null }
}

while ((Get-Date) -lt $deadline) {
    $ts = Get-Date -Format 'HH:mm:ss'
    $lines = @()
    # 1. API state
    try {
        $st = Invoke-RestMethod -Uri 'http://127.0.0.1:8011/api/v1/live-runtime-state/' -TimeoutSec 8
        $lines += "STATE=$($st.state) halted=$($st.entry_halted) reason=$($st.reason)"
    } catch { $lines += "STATE=API_ERR $($_.Exception.Message)" }
    # 2. process alive
    $proc = Get-Process -Id 10908 -ErrorAction SilentlyContinue
    $lines += "PROC=$(if ($proc) {'alive cpu=' + [int]$proc.CPU} else {'DEAD'})"
    # 3. new order decisions
    $od = Read-New $orderFile ([ref]$orderOffset)
    if ($od) {
        $hits = ($od -split "`n") | Where-Object { $_ -match 'ORDER|order|intent|FILL|fill' }
        foreach ($h in ($hits | Select-Object -First 6)) { $lines += "ORDER>> " + $h.Substring(0,[Math]::Min(400,$h.Length)) }
    }
    # 4. new telemetry scorecards (last one only)
    $td = Read-New $teleFile ([ref]$teleOffset)
    if ($td) {
        $sc = ($td -split "`n") | Where-Object { $_ -match 'decision_scorecard|ORDER|fill|submit' } | Select-Object -Last 3
        foreach ($h in $sc) {
            if ($h.Length -gt 500) { $h = $h.Substring(0,500) + '...' }
            $lines += "TELEM>> " + $h
        }
    }
    Add-Content -Path $outFile -Value ("=== $ts ===`n" + ($lines -join "`n")) -Encoding utf8
    Start-Sleep -Seconds 45
}
"rt-monitor end $(Get-Date -Format o)" | Out-File $outFile -Append -Encoding utf8
