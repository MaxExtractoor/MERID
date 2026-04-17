@echo off
REM MERID — Windows Startup Script
REM Run from PowerShell: .\start.bat

cd /d %~dp0

echo [MERID] Installing/verifying dependencies...
py -m pip install -r requirements.txt --quiet

echo [MERID] Starting backend on port 8011...
py -m uvicorn web.main:app --host 0.0.0.0 --port 8011 --log-level info
