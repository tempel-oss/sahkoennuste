
@echo off
cd /d "%~dp0"
python scripts\cloud_runner.py
if errorlevel 1 (
  echo [VIRHE] Pilviajon testaus epaonnistui.
  pause
  exit /b 1
)
python scripts\cloud_validate.py
pause
