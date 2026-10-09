@echo off
REM Kalshi Event Dashboard Startup Script (Windows)

echo 🚀 Starting Kalshi Event Dashboard...
echo 📋 Prerequisites:
echo    1. FastAPI server running on http://localhost:8000
echo    2. Kalshi event bus initialized and emitting events
echo    3. Streamlit dashboard dependencies installed
echo.

REM Check if Python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Python not found. Please install Python first.
    pause
    exit /b 1
)

REM Check if requirements are installed
echo 🔍 Checking dependencies...
python -c "import streamlit, plotly, pandas, requests" >nul 2>&1
if %errorlevel% neq 0 (
    echo 📦 Installing dashboard dependencies...
    pip install -r requirements_dashboard.txt
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
    echo    python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
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

REM Start Streamlit dashboard
echo.
echo 🚀 Starting Streamlit dashboard...
echo 🌐 Dashboard will be available at: http://localhost:8501
echo 📊 Open your browser and navigate to the dashboard URL
echo.
echo 🔄 The dashboard will auto-refresh every 2 seconds
echo ⚙️  Use the sidebar to filter events and control refresh
echo.

REM Start Streamlit
streamlit run kalshi_event_dashboard.py --server.port 8501 --server.address 0.0.0.0 --server.headless false --browser.gatherUsageStats false

pause
