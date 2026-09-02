@echo off
cd /d "%~dp0"
python scripts\score_price_forecasts.py
python scripts\show_forecast_quality.py
pause
