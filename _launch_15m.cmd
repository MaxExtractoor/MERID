@echo off
cd /d C:\Dev\MERID
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ts=Get-Date -Format 'yyyyMMdd_HHmmss'; & C:\Dev\MERID\start_15m.ps1 *> C:\Dev\MERID\logs\server_console_$ts.log"
