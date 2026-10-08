@echo off
REM ============================================================
REM  IDS PH - DEA Logger (+ embedded NaviTool 2.0) - BUILD
REM  Standard build: venv + requirements + PyInstaller, built via
REM  %TEMP% (never in-place, so cloud-sync locks can't corrupt it),
REM  then the finished exe is copied to dist\ and launched so you
REM  can debug/test immediately. dist\ also collects every rollout
REM  file (install/uninstall scripts, version tag, config seed,
REM  offline admin-links fallback) so the whole folder is the
REM  copy-paste handout package for the shared drive.
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
    --icon "%~dp0assets\icon.ico" ^
    --add-data "%~dp0assets\icon.ico;assets" ^
    --add-data "%~dp0admin_links.json;." ^
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
    --hidden-import client.latest_details_tab ^
    --hidden-import client.link_generator_tab ^
    --hidden-import tkinterdnd2 ^
    --hidden-import tkinterdnd2.TkinterDnD ^
    --add-data "%~dp0.venv\Lib\site-packages\tkinterdnd2\tkdnd;tkinterdnd2\tkdnd" ^
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
REM The running exe locks its own file, so a rebuild cannot overwrite it
REM while it (or a previous debug launch) is still open - stop any such
REM instances first. This only touches IDS_DEA_Logger.exe test launches;
REM shared-drive log data is never affected.
taskkill /IM "%EXE_NAME%" /F >nul 2>&1
if not exist "dist" mkdir "dist"
copy /Y "%DIST_TMP%\%EXE_NAME%" "dist\%EXE_NAME%" >nul
if errorlevel 1 (
    echo ERROR: could not write dist\%EXE_NAME% - it is still locked by a
    echo        running copy. Close every IDS_DEA_Logger window including
    echo        its system tray icon, then re-run build.
    pause
    exit /b 1
)
rmdir /S /Q "%BUILD_TMP%" >nul 2>&1
rmdir /S /Q "%DIST_TMP%" >nul 2>&1
REM Stamp the release tag the app's auto-updater (and anyone rolling out)
REM reads to tell which build this is - copy it next to the exe on the
REM shared drive at rollout time.
"%VENV_PY%" -c "import sys; sys.path.insert(0, '.'); from shared.constants import APP_VERSION; open('dist/version.txt', 'w').write(APP_VERSION)"
if exist "dist\version.txt" (
    echo       OK - release tag written to dist\version.txt
)
REM Stage the full rollout handout into dist\ so it can be copied to
REM the shared drive as-is (install.bat already resolves the exe,
REM config seed, and admin-links fallback from its own folder when no
REM dist\ subfolder sits next to it). The config seed is first-install
REM only - install.bat never overwrites a live shared config.
copy /Y "%~dp0install.bat" "dist\install.bat" >nul
copy /Y "%~dp0uninstall.bat" "dist\uninstall.bat" >nul
REM The live shared folder is authoritative for the config and admin
REM links, so they are NEVER staged here - and any copies a previous
REM build left behind are removed so they can't be pasted over it.
if exist "dist\DEA_Config.xlsx" del "dist\DEA_Config.xlsx" >nul 2>&1
if exist "dist\admin_links.json" del "dist\admin_links.json" >nul 2>&1
echo       OK - dist\ now holds the safe handout only: exe + version.txt +
echo       install.bat + uninstall.bat (never the live config/admin links)

echo.
echo ============================================================
echo  BUILD COMPLETE: dist\ is the rollout package (copy it whole
echo  to the shared drive; installed apps self-update from it).
echo  Launching the fresh exe now for debug/test...
echo ============================================================
start "" "%~dp0dist\%EXE_NAME%"
endlocal
