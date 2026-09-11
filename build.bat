@echo off
REM ============================================================
REM  IDS PH - DEA Logger (+ embedded Job Navigator) - BUILD
REM  Standard build: venv + requirements + PyInstaller, built via
REM  %TEMP% (never in-place, so cloud-sync locks can't corrupt it),
REM  then the finished exe is copied to dist\ and launched so you
REM  can debug/test immediately.
REM ============================================================

setlocal EnableExtensions
cd /d "%~dp0"

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "BUILD_TMP=%TEMP%\dea_build_work"
set "DIST_TMP=%TEMP%\dea_build_dist"
set "EXE_NAME=IDS_DEA_Logger.exe"

echo.
echo [1/4] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python was not found on PATH. Install Python 3.9+ from python.org
    echo        and make sure "Add python.exe to PATH" is checked during install.
    pause
    exit /b 1
)

echo.
echo [2/4] Ensuring venv (.venv) + requirements...
if not exist "%VENV_PY%" (
    echo       Creating .venv...
    python -m venv ".venv"
    if errorlevel 1 (
        echo ERROR: could not create .venv.
        pause
        exit /b 1
    )
)
"%VENV_PY%" -m pip install --upgrade pip >nul
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: pip install failed. Check your internet connection.
    pause
    exit /b 1
)
echo       OK - dependencies installed in .venv.

echo.
echo [3/4] Building %EXE_NAME% via %TEMP% ...
echo       (matplotlib makes this take a few minutes and the exe large)
if exist "%BUILD_TMP%" rmdir /S /Q "%BUILD_TMP%"
if exist "%DIST_TMP%" rmdir /S /Q "%DIST_TMP%"
"%VENV_PY%" -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name "IDS_DEA_Logger" ^
    --icon "assets\icon.ico" ^
    --add-data "assets\icon.ico;assets" ^
    --add-data "admin_links.json;." ^
    --workpath "%BUILD_TMP%" ^
    --distpath "%DIST_TMP%" ^
    --specpath "%BUILD_TMP%" ^
    --hidden-import client ^
    --hidden-import client.main_app ^
    --hidden-import client.admin_dashboard ^
    --hidden-import client.calendar_widget ^
    --hidden-import client.local_settings ^
    --hidden-import client.autocomplete ^
    --hidden-import client.autostart ^
    --hidden-import client.shortcuts ^
    --hidden-import client.tray ^
    --hidden-import client.hotkey ^
    --hidden-import client.personal_dashboard ^
    --hidden-import client.cutoff_summary_dialog ^
    --hidden-import client.admin_efficiency_dialog ^
    --hidden-import client.efficiency_view ^
    --hidden-import client.navigator_tab ^
    --hidden-import shared ^
    --hidden-import shared.constants ^
    --hidden-import shared.config_manager ^
    --hidden-import shared.data_store ^
    --hidden-import shared.pathutils ^
    --hidden-import shared.applog ^
    --hidden-import pystray ^
    --hidden-import pystray._win32 ^
    --hidden-import PIL ^
    --hidden-import PIL._tkinter_finder ^
    --collect-submodules pystray ^
    --hidden-import matplotlib.backends.backend_tkagg ^
    --collect-data matplotlib ^
    --copy-metadata matplotlib ^
    dea_logger_entry.py

if errorlevel 1 (
    echo.
    echo BUILD FAILED. Scroll up for the PyInstaller error.
    pause
    exit /b 1
)

echo.
echo [4/4] Publishing to dist\ and launching...
if not exist "dist" mkdir "dist"
copy /Y "%DIST_TMP%\%EXE_NAME%" "dist\%EXE_NAME%" >nul
if not exist "dist\%EXE_NAME%" (
    echo ERROR: built exe did not land in dist\. Check %DIST_TMP%.
    pause
    exit /b 1
)
rmdir /S /Q "%BUILD_TMP%" >nul 2>&1
rmdir /S /Q "%DIST_TMP%" >nul 2>&1

echo.
echo ============================================================
echo  BUILD COMPLETE: dist\%EXE_NAME%
echo  Launching it now for debug/test...
echo ============================================================
start "" "%~dp0dist\%EXE_NAME%"
endlocal
