@echo off
setlocal enabledelayedexpansion

echo =======================================================
echo   NISAR-Pulse: GitHub Initialization & Push Script
echo =======================================================
echo.

:: Check if git command exists
where git >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Git is not found in your system PATH!
    echo.
    echo To install Git on Windows, open a Terminal or PowerShell and run:
    echo     winget install --id Git.Git -e --source winget
    echo.
    echo Or download Git for Windows from: https://git-scm.com/download/win
    echo After installing, restart this script.
    echo.
    pause
    exit /b 1
)

echo [1/5] Checking Git repository status...
if not exist ".git" (
    echo Initializing fresh Git repository...
    git init
) else (
    echo Existing Git repository detected.
)

echo.
echo [2/5] Staging files for commit...
git add .

echo.
echo [3/5] Creating commit...
git commit -m "Deploy NISAR-Pulse: full-stack SAR disaster platform with Docker & Render config"
git branch -M main

echo.
echo [4/5] GitHub Remote Configuration:
set /p REPO_URL="Enter your GitHub repository URL (e.g., https://github.com/username/nisar-pulse.git): "

if "%REPO_URL%"=="" (
    echo [NOTICE] No repository URL provided.
    echo You can add it later using:
    echo     git remote add origin ^<your-github-url^>
    echo     git push -u origin main
    echo.
    pause
    exit /b 0
)

:: Remove existing origin if present
git remote remove origin >nul 2>nul
git remote add origin %REPO_URL%

echo.
echo [5/5] Pushing to GitHub (main branch)...
git push -u origin main

if %errorlevel% equ 0 (
    echo.
    echo =======================================================
    echo   SUCCESS! Project uploaded to GitHub.
    echo =======================================================
    echo.
    echo Next Steps on Render (https://dashboard.render.com):
    echo   1. Click "New +" and select "Blueprint".
    echo   2. Connect your GitHub repository.
    echo   3. Render will automatically read render.yaml and deploy!
    echo.
) else (
    echo.
    echo [WARNING] Git push failed. Please check your credentials or repo permissions.
    echo You can manually run:
    echo     git push -u origin main
)

pause
