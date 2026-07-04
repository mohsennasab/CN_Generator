@echo off
setlocal EnableExtensions

cd /d "%~dp0"

set "TARGET_PATH=%~dp0CN_Generator.bat"
set "ICON_PATH=%~dp0Logo\CN_Generator.ico"
set "SHORTCUT_SCRIPT=%~dp0tools\create_shortcut.ps1"
set "DESKTOP_DIR="
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "DESKTOP_DIR=%%D"
if not defined DESKTOP_DIR set "DESKTOP_DIR=%USERPROFILE%\Desktop"
set "DESKTOP_SHORTCUT=%DESKTOP_DIR%\CN_Generator.lnk"

if not exist "%TARGET_PATH%" (
    echo Could not find CN_Generator.bat.
    pause
    exit /b 1
)

if not exist "%ICON_PATH%" (
    echo Could not find Logo\CN_Generator.ico.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%SHORTCUT_SCRIPT%" -TargetPath "%TARGET_PATH%" -ShortcutPath "%DESKTOP_SHORTCUT%" -IconPath "%ICON_PATH%"
if errorlevel 1 (
    echo Could not create the Desktop shortcut.
    pause
    exit /b 1
)

echo.
echo Desktop shortcut created:
echo %DESKTOP_SHORTCUT%
pause
