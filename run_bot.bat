@echo off
title DARK INFINITE Bot
color 0C
cd /d "%~dp0"

echo.
echo  =============================================
echo   DARK INFINITE Bot - PC Launcher
echo  =============================================
echo.

:: ── Check Python ──
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not installed!
    echo Download from: https://python.org
    pause
    exit /b 1
)

:: ── Load or ask for TOKEN ──
if exist "token.txt" (
    set /p TOKEN=<"token.txt"
    echo [OK] Token loaded from token.txt
) else (
    echo [!] First time setup - enter your bot token.
    set /p TOKEN=Bot TOKEN: 
    echo %TOKEN%>"token.txt"
    echo [OK] Token saved to token.txt
)
set TOKEN=%TOKEN%

:: ── Install requirements once ──
if not exist ".deps_installed" (
    echo [*] Installing requirements (first time only)...
    pip install -r requirements.txt -q --disable-pip-version-check
    echo done>.deps_installed
    echo [OK] Done.
)

:: ── Write a helper checker script ──
echo import urllib.request, sys > check_online.py
echo url = open('replit_url.txt').read().strip() if open.__module__ else '' >> check_online.py
echo: >> check_online.py

(
echo import urllib.request, sys, os
echo try:
echo     f = open('replit_url.txt', 'r'^)
echo     url = f.read(^).strip(^)
echo     f.close(^)
echo     if not url: raise Exception('empty'^)
echo     urllib.request.urlopen(url + '/api/stats', timeout=5^)
echo     print('ONLINE'^)
echo except:
echo     print('OFFLINE'^)
) > check_online.py

echo.
echo [*] DARK INFINITE Bot is starting...
echo [*] Press Ctrl+C anytime to stop.
echo.

:LOOP
    :: Check if Replit bot is online
    if exist "replit_url.txt" (
        python check_online.py > __st.tmp 2>nul
        set /p STATUS=<__st.tmp
        del __st.tmp 2>nul
    ) else (
        set STATUS=OFFLINE
    )

    if "%STATUS%"=="ONLINE" (
        echo [%TIME%] Replit bot ONLINE - sleeping 60s...
        timeout /t 60 /nobreak >nul
        goto LOOP
    )

    echo [%TIME%] Starting bot locally...
    python CodeX.py

    echo.
    echo [%TIME%] Bot crashed or stopped. Restarting in 10s...
    timeout /t 10 /nobreak >nul
    goto LOOP
