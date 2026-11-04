@echo off
title RIPL Email Alert System
echo =======================================
echo   RIPL Email Alert System
echo   Sender  : shwetabh@reclinersindia.com
echo   Recipient: dileep.kumar@reclinersindia.com
echo =======================================
echo.

:: Install dependencies if not already installed
echo Installing dependencies...
pip install python-dotenv --quiet

echo.
echo Starting alert system...
echo Press Ctrl+C to stop.
echo.

:: Run the alert system
python example_usage.py

pause
