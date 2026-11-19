# Silent Process Exit monitoring for python.exe.
# Requires elevation (HKLM writes + service control).  Image-keyed: applies
# to ALL python.exe processes started after the flag is set.
#
# 2026-11-03: WerSvc was found Disabled - SPE local dumps (ReportingMode=2)
# route through the WER fault machinery, so nothing fired.  This script now
# enables WerSvc (Manual, started on demand) AND sets ReportingMode=3 so a
# kernel-launched monitor (ProcDump full dump on the exiting pid) covers the
# path even if WER plumbing is unavailable.
# Rollback: delete SilentProcessExit\python.exe, clear the 0x200 bit from
# IFEO\python.exe\GlobalFlag, restore WerSvc prior start type if changed.

$ifeo = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\python.exe'
$spe  = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\SilentProcessExit\python.exe'

# Export existing state for rollback
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
reg export "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\python.exe" "C:\Dev\MERID\logs\ifeo_python_backup_$stamp.reg" /y 2>$null | Out-Null
Get-Service WerSvc -ErrorAction SilentlyContinue | Select-Object Name,Status,StartType | Out-File "C:\Dev\MERID\logs\wersvc_prior_$stamp.txt"

# WER service is required for native SPE local dumps
Set-Service WerSvc -StartupType Manual
Start-Service WerSvc -ErrorAction SilentlyContinue

$cur = Get-ItemProperty -Path $ifeo -ErrorAction SilentlyContinue
$gf = 0x200
if ($cur.GlobalFlag) { $gf = [int]$cur.GlobalFlag -bor 0x200 }
New-Item -Path $ifeo -Force | Out-Null
Set-ItemProperty -Path $ifeo -Name GlobalFlag -Value $gf -Type DWord

New-Item -Path $spe -Force | Out-Null
# ReportingMode=2 (native local dumps ONLY).  Do NOT use mode 3/MonitorProcess:
# procdump cannot dump a suspended-exit process, the monitor hangs, and the
# exiting process lingers as a zombie that still reports HasExited=false -
# which would blind the watchdog to a real live-server death.
Set-ItemProperty -Path $spe -Name ReportingMode -Value 2 -Type DWord        # native local dumps via WER
Set-ItemProperty -Path $spe -Name IgnoreSelfExits -Value 0 -Type DWord      # capture self + external terminations
Set-ItemProperty -Path $spe -Name LocalDumpFolder -Value 'C:\Dev\MERID\logs\dumps' -Type ExpandString
Set-ItemProperty -Path $spe -Name MaxNumberOfDumpFiles -Value 10 -Type DWord
Set-ItemProperty -Path $spe -Name DumpType -Value 2 -Type DWord             # full dump (gflags-equivalent)
Remove-ItemProperty -Path $spe -Name MonitorProcess -ErrorAction SilentlyContinue
Remove-ItemProperty -Path $spe -Name MonitorCommandLine -ErrorAction SilentlyContinue

Write-Host "IFEO GlobalFlag = $gf"
Get-Service WerSvc | Select-Object Name,Status,StartType
Get-ItemProperty -Path $spe | Format-List ReportingMode,IgnoreSelfExits,LocalDumpFolder,MaxNumberOfDumpFiles,DumpType,MonitorProcess
Write-Host "DONE - validate with a disposable python process then check dumps dir + Event Log source Process Exit Monitor"
