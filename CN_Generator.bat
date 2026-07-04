@echo off
setlocal EnableExtensions EnableDelayedExpansion

title CN Generator
cd /d "%~dp0"

set "APP_NAME=CN Generator"
set "VENV_DIR=%~dp0.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "REQ_FILE=%~dp0requirements.txt"
set "REQ_HASH_FILE=%VENV_DIR%\.requirements.sha256"
set "SHORTCUT_PATH=%~dp0CN_Generator.lnk"
set "SHORTCUT_SCRIPT=%~dp0tools\create_shortcut.ps1"
set "INSTALL_SCRIPT=%~dp0tools\install_dependencies.ps1"
set "ICON_PATH=%~dp0Logo\CN_Generator.ico"

set "CN_SERVER_NAME=127.0.0.1"
set "CN_OPEN_BROWSER=1"
set "CN_SHARE=0"
set "GRADIO_ANALYTICS_ENABLED=False"
set "NO_PROXY=127.0.0.1,localhost,%NO_PROXY%"
set "no_proxy=127.0.0.1,localhost,%no_proxy%"

if exist "%SHORTCUT_SCRIPT%" if exist "%ICON_PATH%" if not exist "%SHORTCUT_PATH%" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%SHORTCUT_SCRIPT%" -TargetPath "%~f0" -ShortcutPath "%SHORTCUT_PATH%" -IconPath "%ICON_PATH%" >nul 2>nul
)

echo.
echo =========================================
echo   %APP_NAME%
echo =========================================
echo.

call :requirements_hash
set "INSTALLED_HASH="
if exist "%REQ_HASH_FILE%" set /p INSTALLED_HASH=<"%REQ_HASH_FILE%"

set "NEEDS_SETUP=0"
if not exist "%VENV_PYTHON%" set "NEEDS_SETUP=1"
if not "%REQ_HASH%"=="%INSTALLED_HASH%" set "NEEDS_SETUP=1"

if "%NEEDS_SETUP%"=="1" (
    powershell -NoProfile -ExecutionPolicy Bypass -STA -File "%INSTALL_SCRIPT%" -VenvDir "%VENV_DIR%" -RequirementsPath "%REQ_FILE%" -HashPath "%REQ_HASH_FILE%"
    if errorlevel 1 goto install_failed
)

echo.
echo Starting the local web app.
if defined CN_SERVER_PORT (
    echo Browser URL: http://%CN_SERVER_NAME%:%CN_SERVER_PORT%
) else (
    echo Browser will open at the first free local port starting at 7860.
)
echo Keep this window open while using the app.
echo.
"%VENV_PYTHON%" app.py
set "APP_EXIT=%ERRORLEVEL%"

echo.
if not "%APP_EXIT%"=="0" (
    echo The app stopped with exit code %APP_EXIT%.
)
echo Press any key to close this window.
pause >nul
exit /b %APP_EXIT%

:requirements_hash
set "REQ_HASH="
for /f "usebackq skip=1 tokens=1" %%H in (`certutil -hashfile "%REQ_FILE%" SHA256 ^| findstr /V /I "CertUtil"`) do (
    if not defined REQ_HASH set "REQ_HASH=%%H"
)
if not defined REQ_HASH set "REQ_HASH=unknown"
exit /b 0

:install_failed
echo Setup did not complete.
echo Check the setup window message, then run this launcher again.
pause
exit /b 1
