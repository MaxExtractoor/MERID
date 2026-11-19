$os = Get-CimInstance Win32_OperatingSystem
$freeGB = [math]::Round($os.FreePhysicalMemory/1MB,1)
$totGB = [math]::Round($os.TotalVisibleMemorySize/1MB,1)
Write-Output "MEM: free=${freeGB}GB total=${totGB}GB"
Get-Process python* -ErrorAction SilentlyContinue | Select-Object Id,@{n='WS_MB';e={[math]::Round($_.WorkingSet64/1MB)}},@{n='CPU_s';e={[math]::Round($_.CPU,0)}},StartTime | Format-Table -AutoSize
$conns = Get-NetTCPConnection -LocalPort 8011 -State Listen -ErrorAction SilentlyContinue
if ($conns) { $conns | Select-Object LocalAddress,LocalPort,OwningProcess | Format-Table -AutoSize } else { Write-Output "PORT 8011: not listening" }
