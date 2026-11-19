$ErrorActionPreference='SilentlyContinue'
$err = 'C:\Dev\MERID\logs\server_console_20261108_040357.err.log'
Write-Host "=== EXEC events ==="
$m = Select-String -Path $err -Pattern 'ORDER_SUBMIT|SUBMITTED|FILLED|ORDER-INTENT-CREATED|CANONICAL-ORDER-INTENT-PASS|EXEC-PATH|order_ack|FILL-INGEST|apply_fill|ENTRY-SUBMIT|insufficient_shard|stale_decision_dropped|LIVE_ENTRIES_HALTED'
if ($m) { $m | Select-Object -Last 25 | ForEach-Object { $_.Line.Substring(0,[Math]::Min(280,$_.Line.Length)) } } else { Write-Host '(none)' }
Write-Host "=== real errors ==="
$m2 = Select-String -Path $err -Pattern 'ERROR \||CRITICAL \||Traceback|LIVE_ENTRIES_HALTED|entry_halted' | Where-Object { $_.Line -notmatch 'CRITICAL-FILTER' }
if ($m2) { $m2 | Select-Object -Last 15 | ForEach-Object { $_.Line.Substring(0,[Math]::Min(250,$_.Line.Length)) } } else { Write-Host '(none)' }
Write-Host "=== state ==="
Get-Content C:\Dev\MERID\_rt_monitor.txt -Tail 300 | Select-String 'STATE=' | Select-Object -Last 2 | ForEach-Object { $_.Line }
Write-Host "=== proc ==="
$p = Get-Process -Id 10908 -ErrorAction SilentlyContinue
if ($p) { Write-Host "PID 10908 alive cpu=$($p.CPU)" } else { Write-Host 'PID 10908 GONE' }
Write-Host "=== fills today ==="
& 'C:\Dev\MERID\.venv\Scripts\python.exe' C:\Dev\MERID\_fills_today.py
