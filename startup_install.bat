@echo off
title DARK INFINITE - Add to Windows Startup
cd /d "%~dp0"
color 0A

echo.
echo  =============================================
echo   DARK INFINITE - Windows Startup Installer
echo  =============================================
echo.

set STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
set SHORTCUT=%STARTUP%\DarkInfiniteBot.bat

echo [*] Adding bot to Windows startup...

:: Create a startup launcher that opens minimized
(
echo @echo off
echo cd /d "%~dp0"
echo start /min cmd /c "run_bot.bat"
) > "%SHORTCUT%"

if exist "%SHORTCUT%" (
    echo [OK] Bot added to startup successfully!
    echo.
    echo     Location: %SHORTCUT%
    echo.
    echo     Every time Windows starts, the bot will
    echo     automatically launch in the background.
    echo.
    echo [*] To remove from startup, run:
    echo     remove_startup.bat
) else (
    echo [ERROR] Failed to add to startup.
    echo Try running as Administrator.
)

echo.
pause
