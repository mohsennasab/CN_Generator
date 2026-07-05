@echo off
setlocal EnableExtensions

cd /d "%~dp0"

set "TARGET_PATH=%~dp0CN_Generator.exe"
set "ICON_PATH=%~dp0CN_Generator.ico"
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

call :create_shortcut "%TARGET_PATH%" "%LOCAL_SHORTCUT%" "%ICON_PATH%"
if errorlevel 1 (
    echo Could not create the folder shortcut.
    pause
    exit /b 1
)

call :create_shortcut "%TARGET_PATH%" "%DESKTOP_SHORTCUT%" "%ICON_PATH%"
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
exit /b 0

:create_shortcut
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%~2'); $s.TargetPath='%~1'; $s.WorkingDirectory='%~dp1'; $s.IconLocation='%~3,0'; $s.Description='Launch CN Generator locally'; $s.Save()"
exit /b %ERRORLEVEL%
