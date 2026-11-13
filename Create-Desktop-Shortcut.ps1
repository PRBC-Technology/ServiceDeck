# Creates a desktop shortcut that starts ServiceDeck.
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$target = Join-Path $here "Run-ServiceDeck.bat"
if (-not (Test-Path $target)) {
  throw "Run-ServiceDeck.bat was not found next to this script."
}
$desktop = [Environment]::GetFolderPath("Desktop")
if (-not $desktop) {
  throw "Could not find the desktop folder."
}
$shortcutPath = Join-Path $desktop "ServiceDeck.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $target
$shortcut.WorkingDirectory = $here
$shortcut.WindowStyle = 1
$shortcut.Description = "ServiceDeck Sunday control dashboard"
$shortcut.Save()
Write-Host "Shortcut created: $shortcutPath"
