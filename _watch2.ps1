$ErrorActionPreference='SilentlyContinue'
$err = 'C:\Dev\MERID\logs\server_console_20261108_050439.err.log'
$log = 'C:\Dev\MERID\_watch2_status.txt'
while ($true) {
    $ts = Get-Date -Format 'HH:mm:ss'
    $proc = Get-Process -Id 10936 -ErrorAction SilentlyContinue
    $procState = if ($proc) { "alive cpu=$([math]::Round($proc.CPU))" } else { 'GONE' }
    $pf = Select-String -Path $err -Pattern 'live_startup_preflight_passed|LIVE_ENTRIES_ENABLED|LIVE_ENTRIES_HALTED|Application startup complete' | Select-Object -Last 3
    $pfLine = if ($pf) { ($pf | ForEach-Object { $_.Line.Substring(0,[Math]::Min(160,$_.Line.Length)) }) -join ' || ' } else { 'preflight pending' }
    $exec = Select-String -Path $err -Pattern 'ORDER_SUBMIT|SUBMITTED|FILLED|ORDER-INTENT-CREATED|CANONICAL-ORDER-INTENT-PASS|EXEC-PATH|FILL-INGEST|apply_fill' | Select-Object -Last 5
    $execLine = if ($exec) { ($exec | ForEach-Object { $_.Line.Substring(0,[Math]::Min(200,$_.Line.Length)) }) -join ' || ' } else { 'no exec events' }
    $errs = Select-String -Path $err -Pattern ' ERROR | CRITICAL |Traceback' | Where-Object { $_.Line -notmatch 'CRITICAL-FILTER|LIVE-RUNTIME-STATE-TRANSITION' } | Select-Object -Last 4
    $errLine = if ($errs) { ($errs | ForEach-Object { $_.Line.Substring(0,[Math]::Min(180,$_.Line.Length)) }) -join ' || ' } else { 'no errors' }
    "=== $ts PROC=$procState" | Out-File $log -Append
    "PF: $pfLine" | Out-File $log -Append
    "EXEC: $execLine" | Out-File $log -Append
    "ERR: $errLine" | Out-File $log -Append
    Start-Sleep -Seconds 120
}
