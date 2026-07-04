@echo off
setlocal EnableExtensions

cd /d "%~dp0"

set "TARGET_PATH=%~dp0CN_Generator.exe"
set "ICON_PATH=%~dp0CN_Generator.ico"
set "SHORTCUT_SCRIPT=%~dp0create_shortcut.ps1"
set "LOCAL_SHORTCUT=%~dp0CN_Generator.lnk"
set "DESKTOP_DIR="

for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "DESKTOP_DIR=%%D"
if not defined DESKTOP_DIR set "DESKTOP_DIR=%USERPROFILE%\Desktop"
set "DESKTOP_SHORTCUT=%DESKTOP_DIR%\CN_Generator.lnk"

if not exist "%TARGET_PATH%" (
    echo Could not find CN_Generator.exe.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%SHORTCUT_SCRIPT%" -TargetPath "%TARGET_PATH%" -ShortcutPath "%LOCAL_SHORTCUT%" -IconPath "%ICON_PATH%"
if errorlevel 1 (
    echo Could not create the folder shortcut.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%SHORTCUT_SCRIPT%" -TargetPath "%TARGET_PATH%" -ShortcutPath "%DESKTOP_SHORTCUT%" -IconPath "%ICON_PATH%"
if errorlevel 1 (
    echo The folder shortcut was created, but the Desktop shortcut could not be created.
    pause
    exit /b 1
)

echo.
echo Shortcuts created.
echo Folder:  %LOCAL_SHORTCUT%
echo Desktop: %DESKTOP_SHORTCUT%
pause
