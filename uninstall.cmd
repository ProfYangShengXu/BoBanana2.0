@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title BoBanana Uninstall

where py >nul 2>&1
if %errorlevel%==0 (
    py -3 "%~dp0uninstall.py" %*
    goto :finish
)
where python >nul 2>&1
if %errorlevel%==0 (
    python "%~dp0uninstall.py" %*
    goto :finish
)
where python3 >nul 2>&1
if %errorlevel%==0 (
    python3 "%~dp0uninstall.py" %*
    goto :finish
)

echo [uninstall] FAIL: Python not found. Run: python uninstall.py
goto :fail

:finish
set ERR=%errorlevel%
if not "%ERR%"=="0" goto :fail
echo.
pause
exit /b 0

:fail
echo.
echo [uninstall] failed - see messages above.
pause
exit /b 1
