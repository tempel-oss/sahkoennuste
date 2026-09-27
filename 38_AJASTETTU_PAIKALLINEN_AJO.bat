@echo off
setlocal
cd /d "%~dp0"

if /I "%~1"=="morning" goto slot_ok
if /I "%~1"=="afternoon" goto slot_ok

echo [VIRHE] Anna slot: morning tai afternoon
exit /b 64

:slot_ok
echo === ELECTRICITY FORECASTER - AJASTETTU PAIKALLINEN AJO (%~1) ===

rem Tama skripti on tarkoitettu Task Schedulerin kutsumaksi, ei kasin ajettavaksi.
rem Toisin kuin 21_AJA_KAIKKI.bat / 30_AJA_JA_JULKAISE.bat, tama EI:
rem   - pysahdy "pause"-komentoon (ajastettu ajo ei voi vastata siihen)
rem   - tee git add/commit/push GitHubiin (live-sivu rakentuu yksinomaan
rem     pilviajosta, joten paikallinen push ei vaikuta siihen mitenkaan ja
rem     tuo vain turhan riskin tormata pilven omiin [skip ci] -committeihin
rem     kahdesti paivassa)
rem Tama vain: 1) ajaa tuotantoputken oikealla issue-slotilla (jotta
rem price_forecast_scores/model_registry -historia karttuu myos iltapaivan
rem tuoreella day-ahead-hinnalla, ei vain aamun ajolla), ja 2) arkistoi
rem paikallisen snapshotin jos archive_forecast_snapshot.py on kaytettavissa.

set "FORECAST_ISSUE_SLOT=%~1"

python scripts\production_runner.py
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo [VIRHE] Tuotantoajo epaonnistui. Exit code: %RC%
    exit /b %RC%
)

if exist archive_forecast_snapshot.py (
    if exist ".venv\Scripts\python.exe" (
        ".venv\Scripts\python.exe" archive_forecast_snapshot.py --root "%CD%" --slot "%~1"
        if errorlevel 1 echo [VAROITUS] Paikallinen snapshot-arkistointi epaonnistui, mutta tuotantoajo onnistui.
    )
)

echo [OK] Ajastettu paikallinen ajo valmis (%~1).
exit /b 0
