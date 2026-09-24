@echo off
REM Windows batch wrapper for setup.py — double-click to run.
setlocal
where python >nul 2>nul
if errorlevel 1 (
    where python3 >nul 2>nul
    if errorlevel 1 (
        echo [setup] Python not found. Install Python 3.11+ from https://python.org
        pause
        exit /b 1
    )
    set PY=python3
) else (
    set PY=python
)
%PY% "%~dp0setup.py"
pause
