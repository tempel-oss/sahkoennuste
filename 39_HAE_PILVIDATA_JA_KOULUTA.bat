@echo off
setlocal
cd /d "%~dp0"

echo === ELECTRICITY FORECASTER - PILVIDATAN HAKU + UUDELLEENKOULUTUS ===
echo (Hakee pilven kartuttaman datan, tuo sen paikalliseen kantaan,
echo  kouluttaa Challenger-mallin uudelleen, ja pushaa tulokset GitHubiin.)
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0sync_cloud_training_data.ps1"
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo [VIRHE] Ajo epaonnistui. Katso tarkempi loki logs-kansiosta ^(sync_*.log^).
) else (
    echo.
    echo [OK] Valmis.
)

exit /b %RC%
