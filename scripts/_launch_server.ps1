$RepoRoot = "C:\Dev\MERID"
$cmd = 'cd /d ' + $RepoRoot + ' && powershell -NoProfile -ExecutionPolicy Bypass -File start_15m.ps1 >> logs\server_console_detached.log 2>&1'
$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine = 'cmd /c "' + $cmd + '"'
    CurrentDirectory = $RepoRoot
}
Write-Output "server launch ReturnValue=$($r.ReturnValue) pid=$($r.ProcessId)"
