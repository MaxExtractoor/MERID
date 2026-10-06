$RepoRoot = "C:\Dev\MERID"
$cmd = 'cd /d ' + $RepoRoot + ' && powershell -NoProfile -ExecutionPolicy Bypass -File scripts\merid_server_watchdog.ps1 >> logs\watchdog_console.log 2>&1'
$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine = 'cmd /c "' + $cmd + '"'
    CurrentDirectory = $RepoRoot
}
Write-Output "watchdog launch ReturnValue=$($r.ReturnValue) pid=$($r.ProcessId)"
