Write-Host "========================================================" -ForegroundColor DarkYellow
Write-Host "       Starting NISAR-Pulse Mission Control" -ForegroundColor Yellow
Write-Host "========================================================" -ForegroundColor DarkYellow
Write-Host ""
Write-Host "Launching server at http://localhost:8000 ..." -ForegroundColor Cyan
Start-Process "http://localhost:8000"
python -m uvicorn main:app --port 8000 --app-dir backend
