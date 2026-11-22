# =======================================================
#   NISAR-Pulse: GitHub Initialization & Push Script (PowerShell)
# =======================================================

Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "  NISAR-Pulse: GitHub Initialization & Push Script" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ""

# Verify git presence
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] Git was not found in your system PATH!" -ForegroundColor Red
    Write-Host "To install Git on Windows, run:" -ForegroundColor Yellow
    Write-Host "    winget install --id Git.Git -e --source winget" -ForegroundColor White
    Write-Host "Or install from: https://git-scm.com/download/win" -ForegroundColor Gray
    Write-Host "After installation, open a new terminal and rerun this script." -ForegroundColor Yellow
    exit 1
}

# 1. Initialize Git
Write-Host "[1/5] Initializing Git repository..." -ForegroundColor Green
if (-not (Test-Path ".git")) {
    git init
} else {
    Write-Host "Existing .git repository found." -ForegroundColor DarkGray
}

# 2. Stage files
Write-Host "[2/5] Staging tracked files..." -ForegroundColor Green
git add .

# 3. Commit
Write-Host "[3/5] Creating commit..." -ForegroundColor Green
git commit -m "Deploy NISAR-Pulse: full-stack SAR disaster platform with Docker & Render config"
git branch -M main

# 4. Prompt for GitHub Remote
Write-Host ""
$repoUrl = Read-Host "Enter your GitHub repository URL (e.g., https://github.com/username/nisar-pulse.git)"

if ([string]::IsNullOrWhiteSpace($repoUrl)) {
    Write-Host "[NOTICE] No repository URL entered. Your local git commit is ready." -ForegroundColor Yellow
    Write-Host "When you create a repository on GitHub, run:" -ForegroundColor White
    Write-Host "    git remote add origin <your-repo-url>" -ForegroundColor Cyan
    Write-Host "    git push -u origin main" -ForegroundColor Cyan
    exit 0
}

# Set remote origin
git remote remove origin 2>$null
git remote add origin $repoUrl.Trim()

# 5. Push
Write-Host "[5/5] Pushing to GitHub (main branch)..." -ForegroundColor Green
git push -u origin main

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "=======================================================" -ForegroundColor Green
    Write-Host "  SUCCESS! Repository successfully pushed to GitHub." -ForegroundColor Green
    Write-Host "=======================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "To deploy on Render (https://dashboard.render.com):" -ForegroundColor Cyan
    Write-Host "  1. Click 'New +' -> 'Blueprint'" -ForegroundColor White
    Write-Host "  2. Select your repository" -ForegroundColor White
    Write-Host "  3. Render will auto-detect render.yaml and launch your web service!" -ForegroundColor White
    Write-Host ""
} else {
    Write-Host "[WARNING] Git push failed. Verify your GitHub login/credentials." -ForegroundColor Red
}
