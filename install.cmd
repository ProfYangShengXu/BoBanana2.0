@echo off
REM BoBanana 2.0 portable installer — double-click to set up on this machine.
title BoBanana 2.0 Install
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
if errorlevel 1 (
    echo.
    echo [install] failed — see messages above.
    pause
    exit /b 1
)
echo.
pause
