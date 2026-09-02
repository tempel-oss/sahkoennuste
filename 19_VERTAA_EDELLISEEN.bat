@echo off
cd /d "%~dp0"
python scripts\build_diagnostics.py >nul
python scripts\show_changes.py
pause
