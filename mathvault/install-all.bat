@echo off
REM Double-click to install + start everything
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-all.ps1"
pause
