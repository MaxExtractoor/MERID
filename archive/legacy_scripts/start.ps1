# MERID Unified Startup Script (PowerShell)
# Starts backend API and React frontend with locked port configuration

Write-Host "=" -NoNewline -ForegroundColor Cyan
Write-Host ("=" * 79) -ForegroundColor Cyan
Write-Host "MERID Unified Startup" -ForegroundColor Green
Write-Host "=" -NoNewline -ForegroundColor Cyan
Write-Host ("=" * 79) -ForegroundColor Cyan
Write-Host ""

# Load environment variables
if (Test-Path ".env") {
    Write-Host "[INFO] Loading .env file..." -ForegroundColor Yellow
    Get-Content .env | ForEach-Object {
        if ($_ -match '^([^=]+)=(.*)$') {
            $name = $matches[1].Trim()
            $value = $matches[2].Trim()
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
} else {
    Write-Host "[WARN] .env file not found, using defaults" -ForegroundColor Yellow
}

# Get ports from environment or use defaults
$BACKEND_PORT = if ($env:MERID_BACKEND_PORT) { $env:MERID_BACKEND_PORT } else { "8000" }
$FRONTEND_PORT = if ($env:MERID_FRONTEND_PORT) { $env:MERID_FRONTEND_PORT } else { "5173" }

# Function to kill process on port
function Kill-ProcessOnPort {
    param($port)
    $connections = netstat -ano | findstr ":$port"
    if ($connections) {
        Write-Host "[WARN] Port $port is already in use, killing existing processes..." -ForegroundColor Yellow
        $connections | ForEach-Object {
            if ($_ -match '\s+(\d+)\s*$') {
                $processId = $matches[1]
                try {
                    taskkill /PID $processId /F 2>&1 | Out-Null
                    Write-Host "  Killed process $processId" -ForegroundColor Gray
                } catch {
                    Write-Host "  Could not kill process $processId" -ForegroundColor Red
                }
            }
        }
        Start-Sleep -Seconds 1
    }
}

# Clean up any existing processes on our ports
Write-Host "[INFO] Checking for existing processes..." -ForegroundColor Yellow
Kill-ProcessOnPort $BACKEND_PORT
Kill-ProcessOnPort $FRONTEND_PORT

Write-Host ""
Write-Host "Starting services:" -ForegroundColor Green
Write-Host "  1. Backend API (FastAPI)  - http://localhost:$BACKEND_PORT" -ForegroundColor Cyan
Write-Host "  2. Frontend (React/Vite)  - http://localhost:$FRONTEND_PORT" -ForegroundColor Cyan
Write-Host ""
Write-Host "Press Ctrl+C to stop all services" -ForegroundColor Yellow
Write-Host "=" -NoNewline -ForegroundColor Cyan
Write-Host ("=" * 79) -ForegroundColor Cyan
Write-Host ""

# Start backend in new window
Write-Host "[1/2] Starting Backend API on port $BACKEND_PORT..." -ForegroundColor Yellow
$backendProcess = Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PWD'; python -m uvicorn web.main:app --host 0.0.0.0 --port $BACKEND_PORT --reload" -PassThru -WindowStyle Normal

Start-Sleep -Seconds 5

# Start frontend in new window
Write-Host "[2/2] Starting React Frontend on port $FRONTEND_PORT..." -ForegroundColor Yellow
$frontendProcess = Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PWD\web\react'; npm run dev" -PassThru -WindowStyle Normal

Start-Sleep -Seconds 3

Write-Host ""
Write-Host "=" -NoNewline -ForegroundColor Cyan
Write-Host ("=" * 79) -ForegroundColor Cyan
Write-Host "All services started successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "Access points:" -ForegroundColor Yellow
Write-Host "  • Backend API:    http://localhost:$BACKEND_PORT" -ForegroundColor Cyan
Write-Host "  • API Docs:       http://localhost:$BACKEND_PORT/docs" -ForegroundColor Cyan
Write-Host "  • React Dashboard: http://localhost:$FRONTEND_PORT" -ForegroundColor Cyan
Write-Host "=" -NoNewline -ForegroundColor Cyan
Write-Host ("=" * 79) -ForegroundColor Cyan
Write-Host ""
Write-Host "Services running in separate windows." -ForegroundColor Green
Write-Host "Close the PowerShell windows to stop services, or press Ctrl+C here." -ForegroundColor Yellow
Write-Host ""

# Wait for user to press Ctrl+C
try {
    while ($true) {
        # Check if processes are still running
        if ($backendProcess.HasExited) {
            Write-Host "[WARN] Backend API process exited" -ForegroundColor Yellow
        }
        if ($frontendProcess.HasExited) {
            Write-Host "[WARN] Frontend process exited" -ForegroundColor Yellow
        }
        
        Start-Sleep -Seconds 5
    }
} catch {
    Write-Host ""
    Write-Host "Shutting down services..." -ForegroundColor Yellow
} finally {
    # Cleanup - kill processes if still running
    if (-not $backendProcess.HasExited) {
        Write-Host "Stopping Backend API..." -ForegroundColor Yellow
        Stop-Process -Id $backendProcess.Id -Force -ErrorAction SilentlyContinue
    }
    
    if (-not $frontendProcess.HasExited) {
        Write-Host "Stopping React Frontend..." -ForegroundColor Yellow
        Stop-Process -Id $frontendProcess.Id -Force -ErrorAction SilentlyContinue
    }
    
    Write-Host ""
    Write-Host "All services stopped." -ForegroundColor Green
}
