@echo off
cd /d "%~dp0"
python camera_app.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: App exited with code %ERRORLEVEL%
    pause
)
