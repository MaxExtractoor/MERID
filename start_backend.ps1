# Start MERID Backend with proper virtual environment
Write-Host "Starting MERID Backend..." -ForegroundColor Cyan

# Activate virtual environment and start backend
& ".\.venv\Scripts\Activate.ps1"
python -m uvicorn web.main:application --host 0.0.0.0 --port 8000 --reload
