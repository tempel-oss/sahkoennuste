
@echo off
cd /d "%~dp0"
echo === Electricity Forecaster v1.3: ajo + julkaisu ===
python scripts\production_runner.py
if errorlevel 1 (
  echo.
  echo [EI JULKAISTA] Tuotantoajo ei valmistunut kokonaan.
  exit /b 1
)
git remote get-url origin >nul 2>&1
if errorlevel 1 (
  echo [VIRHE] GitHub-repositorya ei ole yhdistetty.
  exit /b 1
)
call 29_JULKAISE_GITHUBIIN.bat
exit /b %ERRORLEVEL%
