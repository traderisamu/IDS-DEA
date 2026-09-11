@echo off
REM ============================================================
REM  IDS PH - DEA Logger - UNINSTALL SCRIPT (per employee PC)
REM ============================================================

setlocal EnableExtensions
set "INSTALL_DIR=%LOCALAPPDATA%\IDS_DEA_Logger"
set "SETTINGS_DIR=%APPDATA%\IDS_DEA_Logger"
set "DESKTOP_DIR="
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')" 2^>nul`) do set "DESKTOP_DIR=%%D"
if not defined DESKTOP_DIR set "DESKTOP_DIR=%USERPROFILE%\Desktop"
set "SHORTCUT_NAME=IDS PH DEA Logger.lnk"
set "STARTMENU_LNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\IDS PH DEA Logger.lnk"
set "FALLBACK_NAME=IDS PH DEA Logger.bat"
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "RUN_KEY=HKCU\Software\Microsoft\Windows\CurrentVersion\Run"

echo This will remove IDS PH DEA Logger from this PC.
echo (Your logged data on the shared network drive is NOT touched.)
echo.
set /p CONFIRM="Continue? (Y/N): "
if /i not "%CONFIRM%"=="Y" exit /b 0

taskkill /IM IDS_DEA_Logger.exe /F >nul 2>&1

reg delete "%RUN_KEY%" /v "IDS_DEA_Logger" /f >nul 2>&1
del "%DESKTOP_DIR%\%SHORTCUT_NAME%" >nul 2>&1
del "%STARTMENU_LNK%" >nul 2>&1
del "%DESKTOP_DIR%\%FALLBACK_NAME%" >nul 2>&1
del "%STARTUP_DIR%\%SHORTCUT_NAME%" >nul 2>&1
rmdir /S /Q "%INSTALL_DIR%" >nul 2>&1

echo.
set /p WIPESETTINGS="Also clear your saved name / local settings? (Y/N): "
if /i "%WIPESETTINGS%"=="Y" rmdir /S /Q "%SETTINGS_DIR%" >nul 2>&1

echo.
echo Uninstalled.
pause
