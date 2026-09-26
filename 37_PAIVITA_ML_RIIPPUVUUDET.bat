@echo off
cd /d "%~dp0"
echo === ML-riippuvuuksien asennus/paivitys (requirements-v1.5.txt + requirements-challenger-v1.txt) ===
if exist ".venv\Scripts\python.exe" (
  set PY=.venv\Scripts\python.exe
) else (
  call :findpython
  if errorlevel 1 goto :eof
)
%PY% -m pip install -r requirements-v1.5.txt -r requirements-challenger-v1.txt
if errorlevel 1 (
  echo.
  echo [VIRHE] pip install epaonnistui. Lock-tiedostoa ei paivitetty.
  pause
  exit /b 1
)
echo.
echo === Kirjoitetaan requirements-v1.5.lock.txt asennetuista tarkoista versioista ===
%PY% scripts\freeze_requirements.py
echo.
echo Valmis. Jos versiot muuttuivat, committaa paivitetty requirements-v1.5.lock.txt gittiin.
pause
goto :eof

:findpython
where py >nul 2>nul && (set PY=py -3& exit /b 0)
where python >nul 2>nul && (set PY=python& exit /b 0)
echo Pythonia ei loytynyt (ei py- eika python-komentoa PATHissa).
pause
exit /b 1
