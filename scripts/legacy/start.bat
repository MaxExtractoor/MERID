@echo off
REM MERID — Windows Startup Script
REM Run from PowerShell: .\start.bat

cd /d %~dp0

echo [MERID] Installing/verifying dependencies...
py -m pip install -r requirements.txt --quiet

REM Determine entrypoint based on profile
if "%MERID_PROFILE%"=="kalshi_crypto_15m_v2" (
    echo [MERID] Using 15m lean entrypoint (web.main_15m_lean:app) for kalshi_crypto_15m_v2 profile
    set ENTRYPOINT=web.main_15m_lean:app
) else (
    echo [MERID] Using legacy entrypoint (web.main:app)
    set ENTRYPOINT=web.main:app
)

echo [MERID] Starting backend on port 8011...
py -m uvicorn %ENTRYPOINT% --host 0.0.0.0 --port 8011 --log-level info
