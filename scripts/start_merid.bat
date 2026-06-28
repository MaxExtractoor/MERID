@echo off
REM MERID 24/7 Trading System Startup Script for Windows
REM Usage: start_merid.bat [--fresh-start]

echo ========================================
echo   MERID Kalshi Trading System
echo   24/7 Automated Trading
echo ========================================
echo.

REM Parse arguments
set FRESH_START=0
if "%1"=="--fresh-start" (
    set FRESH_START=1
    echo WARNING: FRESH START MODE - All state will be reset
    echo.
)

REM Find MERID directory
set SCRIPT_DIR=%~dp0
set MERID_DIR=%SCRIPT_DIR%..
cd /d "%MERID_DIR%"

echo Working directory: %MERID_DIR%

REM Load environment
if exist "%USERPROFILE%\.merid_env" (
    echo Loading environment from %USERPROFILE%\.merid_env
    for /f "delims=" %%x in (%USERPROFILE%\.merid_env) do set %%x
) else if exist ".env" (
    echo Loading environment from .env
    REM Parse .env file
    for /f "delims=" %%x in (.env) do set %%x
) else (
    echo No environment file found. Using defaults.
)

REM Check Python environment
if exist ".venv\Scripts\activate.bat" (
    echo Activating virtual environment
    call .venv\Scripts\activate.bat
) else if exist "venv\Scripts\activate.bat" (
    echo Activating virtual environment
    call venv\Scripts\activate.bat
) else (
    echo ERROR: No virtual environment found
    echo Run: python -m venv .venv
    exit /b 1
)

REM Pre-flight checks
echo.
echo Pre-flight Checks
echo ------------------------

REM Check Python
python --version

REM Check disk space
echo Checking disk space...
for /f "tokens=3" %%a in ('dir /-c . ^| findstr "bytes free"') do set FREE_BYTES=%%a
set FREE_GB=%FREE_BYTES:~0,-9%
if not defined FREE_GB set FREE_GB=0
echo Free space: %FREE_GB% GB

REM Check Kalshi API
echo Checking Kalshi API...
curl -s --max-time 10 "https://api.elections.kalshi.com/trade-api/v2/markets" > nul 2>&1
if %errorlevel%==0 (
    echo Kalshi API: OK
) else (
    echo ERROR: Kalshi API unreachable
    echo Check internet connection
    exit /b 1
)

REM Check data directories
echo Checking directories...
if not exist "data" mkdir data
if not exist "logs" mkdir logs

REM Check for stale locks
echo Checking for stale process locks...
set PID_FILE=logs\merid.pid
if exist "%PID_FILE%" (
    echo Found existing PID file
    echo Use: taskkill /F /IM python.exe ^&^& timeout /t 5 ^&^& start_merid.bat
    exit /b 1
)

REM Set environment for fresh start if requested
if "%FRESH_START%"=="1" (
    echo.
    echo Resetting all state...
    set MERID_FRESH_START=1
    
    REM Backup old data
    set BACKUP_DIR=data\backup\%date:~-4,4%%date:~-10,2%%date:~-7,2%_%time:~0,2%%time:~3,2%%time:~6,2%
    set BACKUP_DIR=%BACKUP_DIR: =0%
    mkdir "%BACKUP_DIR%" 2>nul
    
    copy data\*.json "%BACKUP_DIR%\" 2>nul
    copy data\*.db "%BACKUP_DIR%\" 2>nul
    echo Backed up old state to %BACKUP_DIR%
) else (
    set MERID_FRESH_START=0
)

REM Start the system
echo.
echo Starting MERID Trading System...
echo ========================================
echo.
echo Environment settings:
echo   KALSHI_CT_PROFILE: %KALSHI_CT_PROFILE%
echo   MERID_PM_TRADING_MODE: %MERID_PM_TRADING_MODE%
echo   KELLY_FRACTION: %MERID_KELLY_MAX_FRACTION%
echo   FRESH_START: %MERID_FRESH_START%
echo.
echo Press Ctrl+C to stop gracefully
echo.

REM Write PID file
echo %~n0 > "%PID_FILE%"

REM Start the server with logging
REM Use uvicorn directly to ensure FastAPI lifespan handlers are invoked
REM Production 15m entrypoint
echo Using production 15m entrypoint (web.main_15m_lean)
uvicorn web.main_15m_lean:app --host 0.0.0.0 --port 8011

REM Cleanup
del "%PID_FILE%" 2>nul
echo MERID stopped
pause
