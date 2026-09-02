@echo off
cd /d "%~dp0"
echo Asennetaan Windows Task Scheduler -tehtava.
echo Oletusaika on 16:15.
set /p AJANKOHTA="Anna kellonaika HH:MM tai paina Enter = 16:15: "
if "%AJANKOHTA%"=="" set AJANKOHTA=16:15
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install_task.ps1" -Time "%AJANKOHTA%"
pause
