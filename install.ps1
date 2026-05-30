<#
.SYNOPSIS
  BoBanana 2.0 portable installer (Windows wrapper → install.py).

.USAGE
  .\install.ps1
  .\install.ps1 -ApiKey sk-xxx -BaseUrl https://api.deepseek.com/v1 -Model deepseek-chat
  .\install.ps1 -SkipApiKey
  .\install.ps1 -Uninstall
#>

[CmdletBinding()]
param(
    [string]$ApiKey = "",
    [string]$BaseUrl = "",
    [string]$Model = "",
    [switch]$SkipApiKey,
    [switch]$SkipTests,
    [switch]$NoShortcut,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallPy = Join-Path $Root "install.py"

if (-not (Test-Path $InstallPy)) {
    Write-Host "[install] install.py not found" -ForegroundColor Red
    exit 1
}

$argsList = @()
if ($Uninstall) { $argsList += "--uninstall" }
if ($ApiKey) { $argsList += "--api-key", $ApiKey }
if ($BaseUrl) { $argsList += "--base-url", $BaseUrl }
if ($Model) { $argsList += "--model", $Model }
if ($SkipApiKey) { $argsList += "--skip-api-key" }
if ($SkipTests) { $argsList += "--skip-tests" }
if ($NoShortcut) { $argsList += "--no-shortcut" }

$py = $null
foreach ($cmd in @("python", "python3")) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        $py = $cmd
        break
    }
}
if (-not $py) {
    Write-Host "[install] Python not found. Install 3.10+ from https://www.python.org/downloads/" -ForegroundColor Red
    exit 1
}

& $py $InstallPy @argsList
exit $LASTEXITCODE
