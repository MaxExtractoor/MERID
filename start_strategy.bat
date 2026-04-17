@echo off
REM Strategy Startup Script (Windows)

echo 🚀 Starting 15M Crypto Strategy...
echo 📋 Prerequisites:
echo    1. Event bus and FastAPI server running
echo    2. Strategy dependencies installed
echo    3. Kalshi API credentials configured
echo.

REM Check if Python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Python not found. Please install Python first.
    pause
    exit /b 1
)

REM Check if strategy dependencies are installed
echo 🔍 Checking strategy dependencies...
python -c "import numpy, pandas, schedule" >nul 2>&1
if %errorlevel% neq 0 (
    echo 📦 Installing strategy dependencies...
    pip install -r requirements_strategy.txt
    if %errorlevel% neq 0 (
        echo ❌ Failed to install dependencies
        pause
        exit /b 1
    )
)

REM Check if FastAPI server is running
echo 🔍 Checking FastAPI server...
curl -s http://localhost:8000/health >nul 2>&1
if %errorlevel% neq 0 (
    echo ⚠️  FastAPI server not detected on http://localhost:8000
    echo 💡 Make sure to start your FastAPI app first:
    echo    python -m uvicorn merid.api.main:app --host 0.0.0.0 --port 8000 --reload
    echo.
    set /p continue="Continue anyway? (y/N): "
    if /i not "%continue%"=="y" (
        echo ❌ Exiting. Please start FastAPI server first.
        pause
        exit /b 1
    )
) else (
    echo ✅ FastAPI server is running
)

REM Start strategy
echo.
echo 🚀 Starting 15M Crypto Strategy...
echo 📊 Strategy will run cycles every 15 minutes
echo 📱 Use strategy_dashboard.py for monitoring
echo 📱 Use Streamlit dashboard at http://localhost:8501
echo.

REM Start strategy manager
python -c "
from merid.strategies.strategy_integration import strategy_manager
strategy_manager.start_strategy()
print('Strategy started. Press Ctrl+C to stop.')
try:
    while True:
        import time
        time.sleep(1)
except KeyboardInterrupt:
    strategy_manager.stop_strategy()
    print('Strategy stopped.')
"

pause
