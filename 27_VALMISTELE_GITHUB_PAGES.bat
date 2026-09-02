
@echo off
cd /d "%~dp0"
git --version >nul 2>&1
if errorlevel 1 (
  echo Git for Windows puuttuu.
  echo Asenna se ensin osoitteesta git-scm.com/download/win
  pause
  exit /b 1
)
if not exist .git (
  git init
  git branch -M main
)
git add output .github VERSION.txt README_V10.md
git commit -m "Initial Electricity Forecaster PWA"
echo Luo nyt GitHubissa TYHJA repository, esim. sahkoennuste.
echo Sen jalkeen aja 28_YHDISTA_GITHUB_REPOON.bat
pause
