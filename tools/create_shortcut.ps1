param(
    [Parameter(Mandatory = $true)]
    [string]$TargetPath,

    [Parameter(Mandatory = $true)]
    [string]$ShortcutPath,

    [Parameter(Mandatory = $true)]
    [string]$IconPath
)

$ErrorActionPreference = "Stop"

$target = (Resolve-Path -LiteralPath $TargetPath).Path
$workingDirectory = Split-Path -Parent $target
$icon = (Resolve-Path -LiteralPath $IconPath).Path

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($ShortcutPath)
$shortcut.TargetPath = $target
$shortcut.WorkingDirectory = $workingDirectory
$shortcut.IconLocation = "$icon,0"
$shortcut.Description = "Launch CN Generator locally"
$shortcut.Save()

Write-Host "Created shortcut: $ShortcutPath"
