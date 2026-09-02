@echo off
cd /d "%~dp0"
chcp 65001 >nul
python scripts\weather_ingest.py
pause
