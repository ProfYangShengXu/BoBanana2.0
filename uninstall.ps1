<#
.SYNOPSIS
  BoBanana uninstaller wrapper (Windows → uninstall.py).

.USAGE
  .\uninstall.ps1
  .\uninstall.ps1 -All -Yes
  .\uninstall.ps1 -Venv -Yes
#>

[CmdletBinding()]
param(
    [switch]$Venv,
    [switch]$Data,
    [switch]$Env,
    [switch]$All,
    [switch]$Yes,
    [switch]$ShortcutOnly
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$UninstallPy = Join-Path $Root "uninstall.py"

if (-not (Test-Path $UninstallPy)) {
    Write-Host "[uninstall] uninstall.py not found" -ForegroundColor Red
    exit 1
}

$argsList = @()
if ($Venv) { $argsList += "--venv" }
if ($Data) { $argsList += "--data" }
if ($Env) { $argsList += "--env" }
if ($All) { $argsList += "--all" }
if ($Yes) { $argsList += "--yes" }
if ($ShortcutOnly) { $argsList += "--shortcut-only" }

$py = $null
foreach ($cmd in @("py", "python", "python3")) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        $py = $cmd
        break
    }
}
if (-not $py) {
    Write-Host "[uninstall] Python not found" -ForegroundColor Red
    exit 1
}

if ($py -eq "py") {
    & py -3 $UninstallPy @argsList
} else {
    & $py $UninstallPy @argsList
}
exit $LASTEXITCODE
