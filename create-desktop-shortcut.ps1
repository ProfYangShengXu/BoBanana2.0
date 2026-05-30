<#
.SYNOPSIS
  Create a Windows desktop shortcut that runs `bb restart` (close → test → launch).

.USAGE
  .\create-desktop-shortcut.ps1           # create / overwrite shortcut
  .\create-desktop-shortcut.ps1 -Remove # delete the shortcut
#>

[CmdletBinding()]
param(
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$BbCmd = Join-Path $Root "bb.cmd"
$ShortcutName = "BoBanana 2.0.lnk"
$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop $ShortcutName

if ($Remove) {
    if (Test-Path $ShortcutPath) {
        Remove-Item $ShortcutPath -Force
        Write-Host "[bb] removed $ShortcutPath" -ForegroundColor Yellow
    } else {
        Write-Host "[bb] shortcut not found: $ShortcutPath" -ForegroundColor Gray
    }
    exit 0
}

if (-not (Test-Path $BbCmd)) {
    throw "bb.cmd not found at $BbCmd"
}

$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($ShortcutPath)
$link.TargetPath = $BbCmd
$link.Arguments = "restart"
$link.WorkingDirectory = $Root
$link.WindowStyle = 1  # Normal window
$link.Description = "BoBanana 2.0 — close running instance, run tests, restart agent"
# Prefer the venv Python icon when available; fall back to cmd.exe.
$PyIcon = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $PyIcon) { $link.IconLocation = "$PyIcon,0" }
$link.Save()

Write-Host "[bb] desktop shortcut created:" -ForegroundColor Green
Write-Host "     $ShortcutPath"
Write-Host "     action: bb restart (close → test → launch)" -ForegroundColor Gray
