@echo off
REM BoBanana 2.0 launcher wrapper for cmd.exe / double-click.
REM Runs bb.ps1 with an execution-policy bypass so no extra setup is needed.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0bb.ps1" %*
