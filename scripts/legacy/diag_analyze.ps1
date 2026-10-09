param([int]$Tail = 1500)
$log = "C:\Dev\MERID\logs\full.log"
$out = "C:\Dev\MERID\diag_result.txt"
$lines = Get-Content $log -Tail $Tail
$msgs = foreach ($l in $lines) {
    try { ($l | ConvertFrom-Json).message } catch { $null }
}
$msgs = $msgs | Where-Object { $_ }

function CountMatch($pattern) {
    ($msgs | Where-Object { $_ -match $pattern }).Count
}

$report = @()
$report += "TAIL=$Tail  total_msgs=$($msgs.Count)"
$report += "--- pipeline stage counts ---"
$report += "select_markets_returned_1 : " + (CountMatch '_select_markets\(\) returned 1')
$report += "ASSET-GATE-INPUT pre_gate=1: " + (CountMatch 'markets_pre_gate=1')
$report += "CHECKPOINT-3              : " + (CountMatch 'CHECKPOINT-3')
$report += "AFTER-GENERATE-CANDIDATES : " + (CountMatch 'AFTER-GENERATE-CANDIDATES')
$report += "OPTIMIZER-RESULT          : " + (CountMatch 'OPTIMIZER-RESULT')
$report += "COLLECT-CANDIDATE-TIMEOUT : " + (CountMatch 'COLLECT-CANDIDATE-TIMEOUT')
$report += "CANDIDATE-GATE            : " + (CountMatch 'CANDIDATE-GATE')
$report += "candidates_built>=1       : " + (CountMatch 'candidates_built=[1-9]')
$report += "VENUE-GATE                : " + (CountMatch 'VENUE-GATE')
$report += "ORDER (any)               : " + (CountMatch '\[ORDER|PLACE-ORDER|ORDER-INTENT|SUBMIT')
$report += "FILL/order_id             : " + (CountMatch 'FILL|order_id')
$report += "--- last 3 OPTIMIZER-RESULT ---"
$report += ($msgs | Where-Object { $_ -match 'OPTIMIZER-RESULT' } | Select-Object -Last 3)
$report += "--- last 3 CANDIDATE-GATE ---"
$report += ($msgs | Where-Object { $_ -match 'CANDIDATE-GATE' } | Select-Object -Last 3)
$report += "--- last 5 ERROR/CRITICAL (non-noise) ---"
$errs = foreach ($l in $lines) {
    try { $o = $l | ConvertFrom-Json; if ($o.level -in @('ERROR','CRITICAL') -and $o.message -notmatch 'GET-ACTIVE-MARKETS|LOOP-TRACE|MISSING_CATALOG') { $o.message } } catch {}
}
$report += ($errs | Group-Object | ForEach-Object { "x$($_.Count): $($_.Name.Substring(0,[Math]::Min(130,$_.Name.Length)))" } | Select-Object -Last 8)
$report += "--- last 3 COLLECT-CANDIDATE-EXCEPTION (raw, truncated) ---"
$excLines = foreach ($l in $lines) {
    if ($l -match 'COLLECT-CANDIDATE-EXCEPTION') { $l.Substring(0, [Math]::Min(600, $l.Length)) }
}
$report += ($excLines | Select-Object -Last 3)
$report | Set-Content $out
Write-Output "WROTE $out"
