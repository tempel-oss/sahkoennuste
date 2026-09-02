
@echo off
cd /d "%~dp0"
echo Electricity Forecaster v1.2 - tuotantoajo
python scripts\production_runner.py
set RC=%ERRORLEVEL%
echo.
if "%RC%"=="0" (
  echo Ajo valmis. Katso output\latest_forecast.html
) else (
  echo Ajo ei valmistunut kokonaan. Exit code %RC%.
  echo GitHubiin ei pidä julkaista vanhaa ennustetta.
)
pause
exit /b %RC%
