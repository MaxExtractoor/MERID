@echo off
title MERID Control Center
cd /d "C:\Dev\MERID"
echo Starting MERID Control Center...
echo.
start "" "http://127.0.0.1:8000"
python -m uvicorn web.main:app --host 127.0.0.1 --port 8000
pause
