@echo off
cd /d "%~dp0"
python launch_all_apps.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: App exited with code %ERRORLEVEL%
    pause
)
