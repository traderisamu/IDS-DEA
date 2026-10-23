@echo off
REM ============================================================
REM  IDS PH - DEA Logger - REPAIR
REM
REM  Fixes "Could not load PyInstaller's embedded PKG archive from
REM  the executable". That message means the installed exe is
REM  truncated (half-copied during an update/install, or trimmed by
REM  antivirus), so it can never start and cannot self-update.
REM  This re-copies the exe from the release folder, verifies size +
REM  SHA256 against manifest.txt, keeps the broken file as .bak, and
REM  launches the app.
REM
REM  Run it from the release folder on the share, or from the Start
REM  Menu ("IDS PH DEA Logger Repair"). No admin rights needed.
REM  Nothing here touches log data or DEA_Config.xlsx.
REM ============================================================

setlocal EnableExtensions
set "INSTALL_DIR=%LOCALAPPDATA%\IDS_DEA_Logger"
set "TARGET_EXE=%INSTALL_DIR%\IDS_DEA_Logger.exe"
set "NEW_EXE=%INSTALL_DIR%\IDS_DEA_Logger.exe.new"
set "SHARED_REL=Shared\Engineering\ENGG PHL\REPORTS\16 Manhour Report LEADERBOARD\DEA App"

REM Where is the release folder? Next to this script when run from the
REM handout, otherwise the path install.bat recorded, otherwise probe
REM the usual Egnyte alias names ("idsinc (2)" etc. on problem PCs).
set "SRC_DIR="
if exist "%~dp0manifest.txt" set "SRC_DIR=%~dp0"
if defined SRC_DIR goto :have_src
if exist "%INSTALL_DIR%\share_path.txt" set /p SRC_DIR=<"%INSTALL_DIR%\share_path.txt"
if defined SRC_DIR if not exist "%SRC_DIR%\manifest.txt" set "SRC_DIR="
if defined SRC_DIR set "SRC_DIR=%SRC_DIR%\"
if defined SRC_DIR goto :have_src
for %%R in ("\\EgnyteDrive\idsinc" "\\EgnyteDrive\idsinc (2)" "\\EgnyteDrive\idsinc (3)" "\\EgnyteDrive\idsinc (4)" "\\EgnyteDrive\idsinc (5)") do call :probe "%%~R"
if not defined SRC_DIR goto :no_src
goto :have_src

:probe
if defined SRC_DIR exit /b 0
if exist "%~1\%SHARED_REL%\manifest.txt" set "SRC_DIR=%~1\%SHARED_REL%\"
exit /b 0

:have_src
set "SRC_EXE=%SRC_DIR%IDS_DEA_Logger.exe"
echo       Release folder: %SRC_DIR%
if not exist "%SRC_EXE%" goto :no_src

REM manifest.txt first line is "<version>|<size>|<sha256>".
set "LINE="
< "%SRC_DIR%manifest.txt" set /p LINE=
set "WANT_SIZE="
set "WANT_SHA="
for /f "tokens=2 delims=|" %%A in ("%LINE%") do set "WANT_SIZE=%%A"
for /f "tokens=3 delims=|" %%A in ("%LINE%") do set "WANT_SHA=%%A"
if not defined WANT_SHA goto :no_manifest

for %%A in ("%SRC_EXE%") do set "SRC_SIZE=%%~zA"
if not "%SRC_SIZE%"=="%WANT_SIZE%" goto :src_bad
call :hash_of "%SRC_EXE%"
if /i not "%HVAL%"=="%WANT_SHA%" goto :src_bad
echo       OK - release exe verified: %WANT_SIZE% bytes, SHA256 %WANT_SHA%

call :hash_of "%TARGET_EXE%"
if /i "%HVAL%"=="%WANT_SHA%" goto :already_ok

echo       Installed exe is missing or does not match the release copy.
echo       Repairing (a running copy is closed first)...
taskkill /IM IDS_DEA_Logger.exe /F >nul 2>&1
timeout /t 2 /nobreak >nul 2>&1
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
if exist "%NEW_EXE%" del "%NEW_EXE%" >nul 2>&1
copy /Y "%SRC_EXE%" "%NEW_EXE%" >nul
if errorlevel 1 goto :copy_failed
for %%A in ("%NEW_EXE%") do set "NEW_SIZE=%%~zA"
if not "%NEW_SIZE%"=="%WANT_SIZE%" goto :copy_failed
call :hash_of "%NEW_EXE%"
if /i not "%HVAL%"=="%WANT_SHA%" goto :copy_failed
if exist "%TARGET_EXE%" copy /Y "%TARGET_EXE%" "%TARGET_EXE%.bak" >nul
move /Y "%NEW_EXE%" "%TARGET_EXE%" >nul
if errorlevel 1 goto :copy_failed
call :hash_of "%TARGET_EXE%"
if /i not "%HVAL%"=="%WANT_SHA%" goto :copy_failed
echo       OK - repaired and verified.
goto :launch

:already_ok
echo       Installed exe already matches the release copy - nothing to do.

:launch
echo.
echo ============================================================
echo  DONE - launching %TARGET_EXE%
echo ============================================================
start "" "%TARGET_EXE%"
pause
exit /b 0

:no_manifest
echo       WARNING - manifest.txt is missing from the release folder, so
echo       the copy cannot be verified. Copy the whole release folder from
echo       the share again (it must include manifest.txt), then re-run.
pause
exit /b 1

:no_src
echo       ERROR - could not find the release folder (needs manifest.txt
echo       and IDS_DEA_Logger.exe).
echo       Run this script from the DEA release folder on the share, or
echo       re-run install.bat from there to refresh the saved path.
pause
exit /b 1

:src_bad
echo       ERROR - the release copy does not match manifest.txt, so it is
echo       probably still syncing or truncated.
echo       Size on disk: %SRC_SIZE%   Expected: %WANT_SIZE%
echo       Wait a minute, then run this again.
pause
exit /b 1

:copy_failed
echo       ERROR - could not write a verified copy to:
echo       %INSTALL_DIR%
echo       Check free disk space and permissions, then retry.
if exist "%NEW_EXE%" del "%NEW_EXE%" >nul 2>&1
pause
exit /b 1

:hash_of
REM %1 = file. Sets HVAL to its SHA-256 (upper-case, no spaces).
set "HVAL="
for /f "skip=1 delims=" %%H in ('certutil -hashfile %1 SHA256 2^>nul') do if not defined HVAL set "HVAL=%%H"
set "HVAL=%HVAL: =%"
exit /b 0
