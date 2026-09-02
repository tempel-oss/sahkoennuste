@echo off
cd /d "%~dp0"
chcp 65001 >nul
python scripts\daily_collect.py
pause
