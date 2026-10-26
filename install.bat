@echo off
REM ============================================================
REM  IDS PH - DEA Logger (+ embedded NaviTool 2.0) - INSTALL (per PC)
REM  Run this from the rollout package - either the dist\ folder
REM  build.bat assembles (exe + this script + config seed together)
REM  or the project folder (it reads the exe out of the dist\
REM  subfolder there). Both layouts work; nothing needs moving.
REM
REM  IMPORTANT: run this from a Command Prompt window (not just by
REM  double-clicking) the first time, so you can read the OK/WARNING
REM  lines below if something needs attention.
REM ============================================================

setlocal EnableExtensions
cd /d "%~dp0"

REM Looks in dist\ first (the normal case when run from the project
REM folder next to build.bat). Falls back to this same folder (the
REM normal case when run from the dist\ rollout package build.bat
REM assembles) - either layout works.
if exist "%~dp0dist\IDS_DEA_Logger.exe" (
    set "SRC_EXE=%~dp0dist\IDS_DEA_Logger.exe"
) else (
    set "SRC_EXE=%~dp0IDS_DEA_Logger.exe"
)
set "INSTALL_DIR=%LOCALAPPDATA%\IDS_DEA_Logger"
set "TARGET_EXE=%INSTALL_DIR%\IDS_DEA_Logger.exe"
set "SHORTCUT_NAME=IDS PH DEA Logger.lnk"
set "FALLBACK_NAME=IDS PH DEA Logger.bat"
set "VBS_HELPER=%TEMP%\dea_make_shortcut.vbs"
set "RUN_KEY=HKCU\Software\Microsoft\Windows\CurrentVersion\Run"

REM Must match shared\constants.py's DEFAULT_SHARED_PATH. Egnyte exposes a
REM share under whatever name is free on that PC, so 'idsinc' can show up
REM as 'idsinc (2)' and the plain path silently stops resolving. Probe the
REM likely names and use the first one that really holds the config; fall
REM back to the plain name so the warnings below still read correctly.
set "SHARED_REL=Shared\Engineering\ENGG PHL\REPORTS\16 Manhour Report LEADERBOARD\DEA App"
set "SHARED_ROOT=\\EgnyteDrive\idsinc\%SHARED_REL%"
if exist "%SHARED_ROOT%\DEA_Config.xlsx" goto :shared_ready
set "SHARED_ROOT=\\EgnyteDrive\idsinc (2)\%SHARED_REL%"
if exist "%SHARED_ROOT%\DEA_Config.xlsx" goto :shared_ready
set "SHARED_ROOT=\\EgnyteDrive\idsinc (3)\%SHARED_REL%"
if exist "%SHARED_ROOT%\DEA_Config.xlsx" goto :shared_ready
set "SHARED_ROOT=\\EgnyteDrive\idsinc (4)\%SHARED_REL%"
if exist "%SHARED_ROOT%\DEA_Config.xlsx" goto :shared_ready
set "SHARED_ROOT=\\EgnyteDrive\idsinc (5)\%SHARED_REL%"
if exist "%SHARED_ROOT%\DEA_Config.xlsx" goto :shared_ready
set "SHARED_ROOT=\\EgnyteDrive\idsinc\%SHARED_REL%"
:shared_ready
echo       Shared folder: %SHARED_ROOT%
set "SRC_CONFIG=%~dp0DEA_Config.xlsx"
set "DEST_CONFIG=%SHARED_ROOT%\DEA_Config.xlsx"

REM Resolve the REAL Desktop folder. %USERPROFILE%\Desktop is wrong on any
REM PC where OneDrive "Known Folder Move" has redirected the Desktop
REM elsewhere (common in managed corporate environments) - using it
REM silently writes the shortcut somewhere the user will never look. This
REM PowerShell call is redirection-aware and always returns the folder
REM Explorer actually shows as "Desktop".
set "DESKTOP_DIR="
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')" 2^>nul`) do set "DESKTOP_DIR=%%D"
if not defined DESKTOP_DIR set "DESKTOP_DIR=%USERPROFILE%\Desktop"
set "DESKTOP_LNK=%DESKTOP_DIR%\%SHORTCUT_NAME%"
set "DESKTOP_FALLBACK=%DESKTOP_DIR%\%FALLBACK_NAME%"

if not exist "%SRC_EXE%" (
    echo ERROR: IDS_DEA_Logger.exe was not found.
    echo        Looked in:  %~dp0dist\IDS_DEA_Logger.exe
    echo        and:        %~dp0IDS_DEA_Logger.exe
    echo        Build it first using build.bat, then run this script
    echo        again from the same folder ^(no need to move anything^).
    pause
    exit /b 1
)

echo.
echo [1/4] Installing to: %INSTALL_DIR%
echo       A running copy must close first - Windows locks a running
echo       exe so overwriting it would fail, and launching afterwards
echo       would leave two copies running at once.
echo       ^(If the app is open with unsent entries, save them first.^)
set /p CLOSEAPP="Close the running DEA Logger (if any) and continue? (Y/N): "
if /i not "%CLOSEAPP%"=="Y" exit /b 0
taskkill /IM IDS_DEA_Logger.exe /F >nul 2>&1
timeout /t 2 /nobreak >nul 2>&1
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

REM Never overwrite a working install with an unverified file: a truncated
REM handout copy is exactly what produces "Could not load PyInstaller's
REM embedded PKG archive from the executable" after an install. Copy to a
REM .new side file, compare size + SHA256 against the source, then rename
REM it into place (a rename either happens or it does not - it can never
REM leave a half-written exe behind). The old exe is kept as .bak.
set "NEW_EXE=%INSTALL_DIR%\IDS_DEA_Logger.exe.new"
for %%A in ("%SRC_EXE%") do set "SRC_SIZE=%%~zA"
if not defined SRC_SIZE goto :src_bad
if %SRC_SIZE% LSS 1048576 goto :src_bad
if exist "%NEW_EXE%" del "%NEW_EXE%" >nul 2>&1
copy /Y "%SRC_EXE%" "%NEW_EXE%" >nul
if errorlevel 1 goto :copy_failed
for %%A in ("%NEW_EXE%") do set "NEW_SIZE=%%~zA"
if not "%NEW_SIZE%"=="%SRC_SIZE%" goto :copy_failed
call :hash_of "%SRC_EXE%"
set "SRC_HASH=%HVAL%"
call :hash_of "%NEW_EXE%"
set "NEW_HASH=%HVAL%"
if not defined SRC_HASH goto :verified
if not defined NEW_HASH goto :copy_failed
if /i not "%SRC_HASH%"=="%NEW_HASH%" goto :copy_failed
:verified
if exist "%TARGET_EXE%" copy /Y "%TARGET_EXE%" "%TARGET_EXE%.bak" >nul
move /Y "%NEW_EXE%" "%TARGET_EXE%" >nul
if errorlevel 1 goto :copy_failed
for %%A in ("%TARGET_EXE%") do set "INST_SIZE=%%~zA"
if not "%INST_SIZE%"=="%SRC_SIZE%" goto :copy_failed
echo       OK - exe copied from: %SRC_EXE%
if defined SRC_HASH echo       OK - verified: %SRC_SIZE% bytes, SHA256 %SRC_HASH%
if not defined SRC_HASH echo       OK - verified by size only: %SRC_SIZE% bytes
REM Remember where the release folder lives, so this script can be re-run
REM from anywhere (the app's own updater reads the same share).
> "%INSTALL_DIR%\share_path.txt" echo %SHARED_ROOT%
if exist "%INSTALL_DIR%\repair.bat" del "%INSTALL_DIR%\repair.bat" >nul 2>&1
REM Offline fallback for the NaviTool 2.0 tab's quick links (used only
REM when the shared drive is unreachable - otherwise the shared copy wins).
if exist "%~dp0admin_links.json" (
    copy /Y "%~dp0admin_links.json" "%INSTALL_DIR%\admin_links.json" >nul
    if exist "%INSTALL_DIR%\admin_links.json" (
        echo       OK - admin_links.json copied alongside exe.
    )
)

echo.
echo [2/4] Checking shared config file on the network drive...
if exist "%DEST_CONFIG%" (
    echo       OK - DEA_Config.xlsx already exists there - leaving it alone
    echo       ^(this is a shared file everyone reads; this script never
    echo       overwrites it once it exists, so nobody's edits get lost^).
) else (
    if not exist "%SHARED_ROOT%\" (
        echo       WARNING - can't reach the shared folder:
        echo       %SHARED_ROOT%
        echo       Skipping the config copy - make sure you can reach that
        echo       network path ^(mapped drive or direct access^), then either
        echo       re-run this script or copy DEA_Config.xlsx there by hand.
    ) else if not exist "%SRC_CONFIG%" (
        echo       WARNING - DEA_Config.xlsx not found next to this script
        echo       ^(%SRC_CONFIG%^) - skipping. The app needs one on the
        echo       shared drive before anyone can log work.
    ) else (
        copy /Y "%SRC_CONFIG%" "%DEST_CONFIG%" >nul
        if exist "%DEST_CONFIG%" (
            echo       OK - first-time setup: copied DEA_Config.xlsx to the shared drive.
        ) else (
            echo       WARNING - could not copy DEA_Config.xlsx to the shared drive.
            echo       Copy it there by hand: %DEST_CONFIG%
        )
    )
)

echo.
echo [3/4] Registering auto-start (Windows Registry Run key)...
REM Done via plain reg.exe - NOT a scripting engine, so this works even
REM in locked-down environments where VBScript/PowerShell are disabled.
REM (The app also re-registers itself every time it's opened manually,
REM as a second safety net - see client/autostart.py.)
reg add "%RUN_KEY%" /v "IDS_DEA_Logger" /t REG_SZ /d "\"%TARGET_EXE%\"" /f >nul
reg query "%RUN_KEY%" /v "IDS_DEA_Logger" >nul 2>&1
if errorlevel 1 (
    echo       WARNING - could not confirm auto-start registration.
    echo       The app will still try to register itself the first time
    echo       someone opens it manually.
) else (
    echo       OK - will start automatically at Windows login.
)

echo.
echo [4/4] Creating Desktop shortcut (at: %DESKTOP_DIR%)...
where cscript.exe >nul 2>&1
if errorlevel 1 (
    echo       cscript.exe not available on this PC - skipping to fallback.
    goto :fallback_shortcut
)

if exist "%VBS_HELPER%" del "%VBS_HELPER%" >nul 2>&1
echo Set oWS = WScript.CreateObject("WScript.Shell") >> "%VBS_HELPER%"
echo sLinkFile = "%DESKTOP_LNK%" >> "%VBS_HELPER%"
echo Set oLink = oWS.CreateShortcut(sLinkFile) >> "%VBS_HELPER%"
echo oLink.TargetPath = "%TARGET_EXE%" >> "%VBS_HELPER%"
echo oLink.WorkingDirectory = "%INSTALL_DIR%" >> "%VBS_HELPER%"
echo oLink.IconLocation = "%TARGET_EXE%, 0" >> "%VBS_HELPER%"
echo oLink.Description = "IDS PH - Daily Employee Accomplishment Logger" >> "%VBS_HELPER%"
echo oLink.Save >> "%VBS_HELPER%"

cscript //nologo //B "%VBS_HELPER%" >nul 2>&1
del "%VBS_HELPER%" >nul 2>&1

if exist "%DESKTOP_LNK%" (
    echo       OK - Desktop shortcut created: %DESKTOP_LNK%
    if exist "%DESKTOP_FALLBACK%" del "%DESKTOP_FALLBACK%" >nul 2>&1
    goto :done
)

:fallback_shortcut
REM WSH/cscript is disabled or blocked on this PC (common in some
REM locked-down corporate environments) - fall back to a plain launcher
REM .bat on the Desktop instead. It won't have the custom icon, but it's
REM guaranteed to work since it only needs cmd.exe itself.
echo       Real shortcut (.lnk) could not be created - using a simple
echo       launcher file instead (this always works, just a plain icon).
if exist "%DESKTOP_FALLBACK%" del "%DESKTOP_FALLBACK%" >nul 2>&1
echo @echo off >> "%DESKTOP_FALLBACK%"
echo start "" "%TARGET_EXE%" >> "%DESKTOP_FALLBACK%"
if exist "%DESKTOP_FALLBACK%" (
    echo       OK - Desktop launcher created: %DESKTOP_FALLBACK%
) else (
    echo       WARNING - could not create anything on the Desktop.
    echo       You can still run the app directly from: %TARGET_EXE%
)

:done
echo.
echo [5/5] Creating Start Menu shortcut...
set "STARTMENU_LNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\IDS PH DEA Logger.lnk"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws=New-Object -ComObject WScript.Shell; $s=$ws.CreateShortcut('%STARTMENU_LNK%'); $s.TargetPath='%TARGET_EXE%'; $s.WorkingDirectory='%INSTALL_DIR%'; $s.Description='IDS PH - Daily Employee Accomplishment Logger'; $s.Save()" >nul 2>&1
if exist "%STARTMENU_LNK%" (
    echo       OK - Start Menu shortcut created.
) else (
    echo       WARNING - Start Menu shortcut could not be created (non-fatal;
    echo       the Desktop shortcut above is the primary launcher^).
)
REM Older builds dropped a "Repair" shortcut here; repair.bat is no longer
REM shipped (re-running this script does the same verified re-copy), so
REM clean both leftovers up.
set "STARTMENU_REPAIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\IDS PH DEA Logger Repair.lnk"
if exist "%STARTMENU_REPAIR%" del "%STARTMENU_REPAIR%" >nul 2>&1
echo.
echo ============================================================
echo  INSTALL COMPLETE
echo ============================================================
echo  Note: the app now starts quietly in the system tray (no
echo  window pops up at login) - click the tray icon anytime to
echo  open it. It also re-creates the Desktop shortcut and
echo  auto-start registration on its own if either ever goes
echo  missing, so this script only needs to run once per PC.
echo.
echo  If the app ever shows "Could not load PyInstaller's embedded
echo  PKG archive", just run this script again from the release
echo  folder - it re-copies the exe, verifies it, and keeps the
echo  broken file as IDS_DEA_Logger.exe.bak.
echo.
set /p LAUNCH="Launch it now? (Y/N): "
if /i "%LAUNCH%"=="Y" start "" "%TARGET_EXE%"

pause
exit /b 0

:hash_of
REM %1 = file. Sets HVAL to its SHA-256 (upper-case, no spaces), or leaves
REM it empty when certutil is unavailable - callers then verify by size.
set "HVAL="
for /f "skip=1 delims=" %%H in ('certutil -hashfile %1 SHA256 2^>nul') do if not defined HVAL set "HVAL=%%H"
set "HVAL=%HVAL: =%"
exit /b 0

:src_bad
echo       ERROR - the handout exe looks truncated (%SRC_SIZE% bytes):
echo       %SRC_EXE%
echo       Re-copy the release folder from the share, then run this again.
pause
exit /b 1

:copy_failed
echo       FAILED to install a verified copy of the exe.
echo       Check permissions on %INSTALL_DIR% and free disk space, then retry.
echo       Any previously installed copy was left untouched.
if exist "%NEW_EXE%" del "%NEW_EXE%" >nul 2>&1
pause
exit /b 1
