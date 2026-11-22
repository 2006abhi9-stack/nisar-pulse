@echo off
echo ========================================================
echo       Starting NISAR-Pulse Mission Control
echo ========================================================
echo.
echo Launching server at http://localhost:8000 ...
start http://localhost:8000
python -m uvicorn main:app --port 8000 --app-dir backend
pause
