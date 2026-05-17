@echo off
title DARK INFINITE - Remove from Startup
color 0E
cd /d "%~dp0"

set SHORTCUT=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\DarkInfiniteBot.bat

if exist "%SHORTCUT%" (
    del "%SHORTCUT%"
    echo [OK] Bot removed from Windows startup.
) else (
    echo [!] Bot was not in startup.
)
echo.
pause
