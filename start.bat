@echo off
rem One-click launcher for the Drug Stability Study Management System (Windows).
rem Double-click this file. Close the console window to stop the server.
rem The first run creates a private virtual environment in .venv\ and installs the
rem dependencies there, so the system Python installation is not changed.
rem Optional: set PORT=8510 before running to use another port.

setlocal EnableExtensions
chcp 65001 >nul
title Drug Stability Study Management System
cd /d "%~dp0"

if "%PORT%"=="" set PORT=8501
set "VENV=%~dp0.venv"
set "VPY=%VENV%\Scripts\python.exe"

rem ---- 1. create the virtual environment on first run ----------------------
if exist "%VPY%" goto have_venv

set "PY="
where py >nul 2>nul && set "PY=py -3"
if "%PY%"=="" where python >nul 2>nul && set "PY=python"
if "%PY%"=="" (
    echo [ERROR] Python was not found.
    echo Install Python 3.9 or newer from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" during installation, then run start.bat again.
    pause
    exit /b 1
)
echo [INFO] First run: creating the virtual environment in .venv ...
%PY% -m venv "%VENV%"
if errorlevel 1 (
    echo [ERROR] Could not create the virtual environment.
    pause
    exit /b 1
)

:have_venv
rem ---- 2. install dependencies when they are missing ------------------------
"%VPY%" -c "import streamlit, pandas, numpy, scipy, matplotlib, plotly, openpyxl, reportlab, bcrypt" >nul 2>nul
if errorlevel 1 (
    echo [INFO] Installing dependencies from requirements.txt ...
    "%VPY%" -m pip install --upgrade pip >nul
    "%VPY%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed. Check your network or pip configuration.
        pause
        exit /b 1
    )
)

rem ---- 3. start the server and open the browser -----------------------------
echo.
echo ============================================================
echo  Starting the system at  http://localhost:%PORT%
echo  The browser will open automatically.
echo  First start: if STAB_ADMIN_PASSWORD is not set, a one-time
echo  password for the 'admin' account is printed below. Change it
echo  after the first login.
echo  Close this window to stop the server.
echo ============================================================
echo.
start "" /b cmd /c "timeout /t 5 /nobreak >nul & start "" http://localhost:%PORT%"
"%VPY%" -m streamlit run app.py --server.port %PORT% --server.headless true --browser.gatherUsageStats false

echo.
echo Server stopped.
pause
endlocal
