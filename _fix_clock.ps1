$log = "C:\Dev\MERID\_fix_clock_result.txt"
try {
    Set-Service w32time -StartupType Automatic -ErrorAction Stop
    Start-Service w32time -ErrorAction Stop
    w32tm /resync /force 2>&1 | Out-File $log -Append
    w32tm /query /status 2>&1 | Out-File $log -Append
    w32tm /query /peers 2>&1 | Out-File $log -Append
    "DONE $(Get-Date -Format o)" | Out-File $log -Append
} catch {
    "ERROR: $_" | Out-File $log -Append
}
