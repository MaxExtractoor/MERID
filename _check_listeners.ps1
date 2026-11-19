$conns = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.OwningProcess -eq 5160 }
if ($conns) { $conns | Select-Object LocalAddress, LocalPort, OwningProcess | Format-Table -AutoSize } else { Write-Output "NO_LISTENERS_FOR_5160" }
$all = Get-NetTCPConnection -LocalPort 8011 -ErrorAction SilentlyContinue
if ($all) { $all | Select-Object LocalAddress, LocalPort, State, OwningProcess | Format-Table -AutoSize } else { Write-Output "NO_8011_ANY_STATE" }
