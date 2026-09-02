@echo off
cd /d "%~dp0"
call :findpython
if errorlevel 1 goto :eof
%PY% scripts\fingrid_check.py
pause
goto :eof
:findpython
where py >nul 2>nul && (set PY=py -3& exit /b 0)
where python >nul 2>nul && (set PY=python& exit /b 0)
echo Pythonia ei loytynyt.
pause
exit /b 1
