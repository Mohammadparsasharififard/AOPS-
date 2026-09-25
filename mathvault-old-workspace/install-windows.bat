@echo off
REM Double-clickable launcher for install-windows.ps1
REM If PowerShell is available, runs the .ps1 with bypass policy.
where powershell >nul 2>nul
if errorlevel 1 (
    echo [install] PowerShell not found. Install Windows 10 or newer.
    pause
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-windows.ps1"
pause
