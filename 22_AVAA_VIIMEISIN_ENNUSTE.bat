@echo off
cd /d "%~dp0"
if not exist output\latest_forecast.html (
  echo Ennustetta ei ole viela julkaistu. Aja ensin 21_AJA_KAIKKI.bat
  pause
  exit /b 1
)
start "" "%~dp0output\latest_forecast.html"
