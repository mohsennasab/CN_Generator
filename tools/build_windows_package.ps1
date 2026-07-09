param(
    [string]$Version = "local",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$icon = Join-Path $projectRoot "Logo\CN_Generator.ico"
$releaseRoot = Join-Path $projectRoot "release"
$packageName = "CN_Generator_Windows_$Version"
$packageDir = Join-Path $releaseRoot $packageName
$zipPath = Join-Path $releaseRoot "$packageName.zip"
$distDir = Join-Path $projectRoot "dist\CN_Generator"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Local venv was not found. Run CN_Generator.bat once first, then rerun this script."
}

if (-not (Test-Path -LiteralPath $icon)) {
    throw "Logo\CN_Generator.ico was not found."
}

New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null

if (-not $SkipBuild) {
    Push-Location $projectRoot
    try {
        & $python -m PyInstaller `
            --noconfirm `
            --clean `
            --onedir `
            --name CN_Generator `
            --icon "$icon" `
            --add-data "Logo;Logo" `
            --add-data "data\gcn10;data\gcn10" `
            --collect-all gradio `
            --collect-all gradio_client `
            --collect-all safehttpx `
            --collect-all groovy `
            --collect-all folium `
            --collect-all branca `
            --collect-all rasterio `
            --collect-all pyogrio `
            --collect-all pyproj `
            --collect-all shapely `
            --collect-all geopandas `
            --collect-all rasterstats `
            --collect-all leafmap `
            --hidden-import sklearn.neighbors._partition_nodes `
            app.py
    }
    finally {
        Pop-Location
    }
}

if (-not (Test-Path -LiteralPath (Join-Path $distDir "CN_Generator.exe"))) {
    throw "Build output was not found at dist\CN_Generator\CN_Generator.exe."
}

if (Test-Path -LiteralPath $packageDir) {
    Remove-Item -LiteralPath $packageDir -Recurse -Force
}

if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}

New-Item -ItemType Directory -Force -Path $packageDir | Out-Null
Get-ChildItem -LiteralPath $distDir -Force | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $packageDir -Recurse -Force
}

$sampleSource = Join-Path $projectRoot "data\HUC10 Example"
$sampleTarget = Join-Path $packageDir "Sample Data\HUC10 Example"
if (Test-Path -LiteralPath $sampleSource) {
    New-Item -ItemType Directory -Force -Path $sampleTarget | Out-Null
    Get-ChildItem -LiteralPath $sampleSource -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $sampleTarget -Recurse -Force
    }
}

Copy-Item -LiteralPath (Join-Path $projectRoot "Logo\CN_Generator.ico") -Destination (Join-Path $packageDir "CN_Generator.ico") -Force
Copy-Item -LiteralPath (Join-Path $projectRoot "tools\package_create_shortcuts.bat") -Destination (Join-Path $packageDir "Create_Shortcuts.bat") -Force
Copy-Item -LiteralPath (Join-Path $projectRoot "tools\PACKAGE_README.txt") -Destination (Join-Path $packageDir "README.txt") -Force
Copy-Item -LiteralPath (Join-Path $projectRoot "LICENSE.md") -Destination (Join-Path $packageDir "LICENSE.txt") -Force

$safehttpxSource = Join-Path $projectRoot ".venv\Lib\site-packages\safehttpx"
$safehttpxTarget = Join-Path $packageDir "_internal\safehttpx"
if ((Test-Path -LiteralPath $safehttpxSource) -and -not (Test-Path -LiteralPath $safehttpxTarget)) {
    Copy-Item -LiteralPath $safehttpxSource -Destination $safehttpxTarget -Recurse -Force
}

$groovySource = Join-Path $projectRoot ".venv\Lib\site-packages\groovy"
$groovyTarget = Join-Path $packageDir "_internal\groovy"
if ((Test-Path -LiteralPath $groovySource) -and -not (Test-Path -LiteralPath $groovyTarget)) {
    Copy-Item -LiteralPath $groovySource -Destination $groovyTarget -Recurse -Force
}

$internalDir = Join-Path $packageDir "_internal"
if (Test-Path -LiteralPath $internalDir) {
    $item = Get-Item -LiteralPath $internalDir -Force
    $item.Attributes = $item.Attributes -bor [System.IO.FileAttributes]::Hidden
}

foreach ($helper in @("CN_Generator.ico")) {
    $helperPath = Join-Path $packageDir $helper
    if (Test-Path -LiteralPath $helperPath) {
        $item = Get-Item -LiteralPath $helperPath -Force
        $item.Attributes = $item.Attributes -bor [System.IO.FileAttributes]::Hidden
    }
}

& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $projectRoot "tools\create_shortcut.ps1") `
    -TargetPath (Join-Path $packageDir "CN_Generator.exe") `
    -ShortcutPath (Join-Path $packageDir "CN_Generator.lnk") `
    -IconPath (Join-Path $packageDir "CN_Generator.ico") | Out-Null

Compress-Archive -LiteralPath $packageDir -DestinationPath $zipPath -Force

Write-Host "Created package folder: $packageDir"
Write-Host "Created zip package:    $zipPath"
