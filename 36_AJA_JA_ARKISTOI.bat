@echo off
setlocal
cd /d "%~dp0"

if /I "%~1"=="morning" goto slot_ok
if /I "%~1"=="afternoon" goto slot_ok

echo [VIRHE] Anna slot: morning tai afternoon
exit /b 64

:slot_ok
echo === ELECTRICITY FORECASTER %~1 ===

set "FORECAST_ISSUE_SLOT=%~1"
call "%CD%\30_AJA_JA_JULKAISE.bat"
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo [VIRHE] Tuotantoajo epaonnistui. Snapshotia ei tallenneta. Exit code: %RC%
    exit /b %RC%
)

"%CD%\.venv\Scripts\python.exe" "%CD%\archive_forecast_snapshot.py" --root "%CD%" --slot "%~1"
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo [VIRHE] Snapshotin tallennus epaonnistui. Exit code: %RC%
    exit /b %RC%
)

echo [OK] Tuotantoajo ja snapshot valmis.
exit /b 0
