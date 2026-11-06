@echo off
cd /d C:\Dev\MERID
set MERID_OBSERVE_ONLY=1
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ts=Get-Date -Format 'yyyyMMdd_HHmmss'; & C:\Dev\MERID\start_15m.ps1 *> C:\Dev\MERID\logs\server_console_observe1_$ts.log"
