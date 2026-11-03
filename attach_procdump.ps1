param(
    [Parameter(Mandatory=$true)][int]$TargetPid,
    [int]$WaitForPidSeconds = 90
)

# Attach Sysinternals ProcDump to the live MERID server process.
# -e  : dump on unhandled (second-chance) native exceptions
# -t  : dump at process termination — captures silent exits with no exception
# -ma : full dump (all memory + handles) for postmortem debugging
# Dumps land in logs\dumps\ — bounded manually; ~500MB per full dump.

$procDump = "C:\Dev\MERID\tools\procdump64.exe"
$dumpDir  = "C:\Dev\MERID\logs\dumps"

if (-not (Test-Path $procDump)) {
    Write-Output "PROCDUMP-MISSING: $procDump not found — download Sysinternals Procdump.zip"
    exit 1
}
New-Item -ItemType Directory -Path $dumpDir -Force | Out-Null

# Wait until the target exists (restart races), then attach.
$deadline = (Get-Date).AddSeconds($WaitForPidSeconds)
while (-not (Get-Process -Id $TargetPid -ErrorAction SilentlyContinue)) {
    if ((Get-Date) -gt $deadline) {
        Write-Output "PROCDUMP-TIMEOUT: pid $TargetPid never appeared"
        exit 1
    }
    Start-Sleep -Seconds 3
}

$proc = Start-Process -FilePath $procDump `
    -ArgumentList "-accepteula -ma -e -t $TargetPid `"$dumpDir`"" `
    -WindowStyle Hidden -PassThru

Write-Output "PROCDUMP-ARMED: pid $($proc.Id) monitoring server pid $TargetPid -> $dumpDir"
exit 0
