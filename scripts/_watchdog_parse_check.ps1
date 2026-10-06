$errs = $null
$tok = $null
[void][System.Management.Automation.PSParser]::Tokenize(
    (Get-Content -Raw 'C:\Dev\MERID\scripts\merid_server_watchdog.ps1'),
    [ref]$errs
)
if ($errs.Count -gt 0) {
    $errs | ForEach-Object { Write-Output ("ERR: " + $_.Message) }
    exit 1
}
Write-Output 'PARSE OK'
exit 0
