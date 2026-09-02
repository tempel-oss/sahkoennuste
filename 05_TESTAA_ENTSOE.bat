@echo off
chcp 65001 >nul
cd /d "%~dp0"
call :findpython
if errorlevel 1 goto :eof
%PY% scripts\entsoe_check.py
set RC=%ERRORLEVEL%
echo.
if "%RC%"=="0" echo TESTI VALMIS: ENTSO-E toimii vahintaan yhdella endpointilla.
if "%RC%"=="2" echo TESTI VALMIS: endpointit eivat palauttaneet API/XML-dataa. Tokenia ei todettu vaaraksi.
if "%RC%"=="3" echo TESTI VALMIS: kayttooikeus/token hylattiin.
if "%RC%"=="4" echo TESTI VALMIS: palvelin vastasi, mutta TimeSeries-dataa ei saatu.
echo.
pause
goto :eof
:findpython
where py >nul 2>nul && (set PY=py -3& exit /b 0)
where python >nul 2>nul && (set PY=python& exit /b 0)
echo Pythonia ei loytynyt.
pause
exit /b 1
