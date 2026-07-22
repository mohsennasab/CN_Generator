param(
    [string]$Version = "local",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$icon = Join-Path $projectRoot "Logo\CN_Generator.ico"
$releaseRoot = Join-Path $projectRoot "release"
$packageName = "Curve_Number_Studio_Windows_$Version"
$packageDir = Join-Path $releaseRoot $packageName
$zipPath = Join-Path $releaseRoot "$packageName.zip"
$distDir = Join-Path $projectRoot "dist\Curve_Number_Studio"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Local venv was not found. Run Curve_Number_Studio.bat once first, then rerun this script."
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
            --name Curve_Number_Studio `
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

if (-not (Test-Path -LiteralPath (Join-Path $distDir "Curve_Number_Studio.exe"))) {
    throw "Build output was not found at dist\Curve_Number_Studio\Curve_Number_Studio.exe."
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

# Zip with .NET so hidden files (the _internal folder) are included.
# Compress-Archive skips hidden files, which produced broken release zips.
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory(
    $packageDir,
    $zipPath,
    [System.IO.Compression.CompressionLevel]::Optimal,
    $true
)

# Verify the zip holds every file from the package folder before shipping it
$folderFiles = @(Get-ChildItem -LiteralPath $packageDir -Recurse -File -Force)
$zip = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
try {
    $zipFiles = @($zip.Entries | Where-Object { $_.Name -ne "" })
    $zipCount = $zipFiles.Count
}
finally {
    $zip.Dispose()
}
if ($zipCount -ne $folderFiles.Count) {
    throw "Zip verification failed: package folder has $($folderFiles.Count) files but the zip has $zipCount. Do not ship this zip."
}
Write-Host "Zip verified: $zipCount files match the package folder."

Write-Host "Created package folder: $packageDir"
Write-Host "Created zip package:    $zipPath"
