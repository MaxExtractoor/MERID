@echo off
REM MERID — Frontend Startup Script
cd /d %~dp0\web\react
echo [MERID] Starting dashboard on http://localhost:5173 ...
npm run dev
