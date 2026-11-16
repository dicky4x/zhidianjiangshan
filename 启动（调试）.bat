@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYCALL=python"
where python >nul 2>&1
if errorlevel 1 (
    where py >nul 2>&1
    if errorlevel 1 (
        echo KeyHint: Python not found. Install Python 3.8+ and run: pip install pillow
        pause
        exit /b 1
    )
    set "PYCALL=py -3"
)
echo KeyHint - debug console (close this window to stop)
echo Python: %PYCALL%
echo.
%PYCALL% app.py
echo.
echo [KeyHint exited]
pause
