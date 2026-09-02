
@echo off
cd /d "%~dp0"
set /p AJANKOHTA="Anna kellonaika HH:MM tai Enter = 16:15: "
if "%AJANKOHTA%"=="" set AJANKOHTA=16:15
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install_cloud_task.ps1" -Time "%AJANKOHTA%"
pause
