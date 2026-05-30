<#
.SYNOPSIS
  BoBanana 2.0 launcher — simplified verbs: start / use / close / restart.

.USAGE
  .\bb.ps1 start            # run tests, then launch the agent
  .\bb.ps1 start --debug    # extra args pass through to the agent
  .\bb.ps1 use              # launch the agent quickly (no tests)
  .\bb.ps1 close            # stop any running bobanana instance
  .\bb.ps1 restart          # close, then start (with tests)
  .\bb.ps1 test             # run selfcheck + offline tests only
  .\bb.ps1 setup            # (re)create venv and install dependencies
  .\bb.ps1 help
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Command = "help",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $Root ".venv"
$Py = Join-Path $VenvDir "Scripts\python.exe"

function Info($msg) { Write-Host "[bb] $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "[bb] $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "[bb] $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "[bb] $msg" -ForegroundColor Red }

function Ensure-Venv {
    if (-not (Test-Path $Py)) {
        Info "creating virtual environment (.venv) ..."
        python -m venv $VenvDir
        Info "installing dependencies ..."
        & $Py -m pip install --upgrade pip -q
        & $Py -m pip install -r (Join-Path $Root "requirements.txt")
        if ($LASTEXITCODE -ne 0) { throw "dependency install failed" }
    }
}

function Invoke-Step($label, [scriptblock]$block) {
    & $block
    if ($LASTEXITCODE -ne 0) { throw "$label failed (exit $LASTEXITCODE)" }
}

function Run-Tests {
    Info "running selfcheck + offline tests ..."
    $env:PYTHONPATH = $Root
    Invoke-Step "selfcheck"           { & $Py -m bobanana --selfcheck }
    Invoke-Step "test_graph_offline"  { & $Py (Join-Path $Root "tests\test_graph_offline.py") }
    Invoke-Step "test_skills_offline" { & $Py (Join-Path $Root "tests\test_skills_offline.py") }
    Ok "all tests passed"
}

function Start-Agent {
    Info "launching agent ... (type /quit to exit)"
    $env:PYTHONPATH = $Root
    & $Py -m bobanana @Rest
}

function Stop-Bobanana {
    $self = $PID
    $procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.ProcessId -ne $self -and
            $_.CommandLine -and
            $_.CommandLine -match "bobanana" -and
            $_.Name -match "python"
        }
    if (-not $procs) { Warn "no running bobanana instance found"; return }
    foreach ($p in $procs) {
        try {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
            Ok "stopped PID $($p.ProcessId)"
        } catch {
            Fail "could not stop PID $($p.ProcessId): $($_.Exception.Message)"
        }
    }
}

function Show-Help {
    Write-Host @"
BoBanana 2.0 — launcher

  bb start [args]   run tests, then launch the agent (args pass through, e.g. --debug)
  bb use   [args]   launch the agent quickly (skips tests)
  bb close          stop any running bobanana instance
  bb restart [args] close, then start (with tests)
  bb test           run selfcheck + offline tests only
  bb setup          (re)create .venv and install dependencies
  bb install [args] full portable install (venv, API key, shortcut) — see INSTALL.md
  bb config         configure API key / base URL / model (interactive)
  bb help           show this help
"@ -ForegroundColor Gray
}

switch ($Command.ToLower()) {
    "start"   { Ensure-Venv; Run-Tests; Start-Agent }
    "use"     { Ensure-Venv; Start-Agent }
    "close"   { Stop-Bobanana }
    "stop"    { Stop-Bobanana }
    "restart" { Stop-Bobanana; Ensure-Venv; Run-Tests; Start-Agent }
    "test"    { Ensure-Venv; Run-Tests }
    "setup"   { if (Test-Path $VenvDir) { Warn ".venv exists; installing/refreshing deps"; & $Py -m pip install -r (Join-Path $Root "requirements.txt") } else { Ensure-Venv }; Ok "setup done" }
    "install" {
        $installPs1 = Join-Path $Root "install.ps1"
        if (-not (Test-Path $installPs1)) { Fail "install.ps1 not found"; exit 1 }
        & powershell -NoProfile -ExecutionPolicy Bypass -File $installPs1 @Rest
    }
    "config" {
        Ensure-Venv
        $env:PYTHONPATH = $Root
        & $Py -m bobanana --configure
    }
    "help"    { Show-Help }
    default   { Fail "unknown command: $Command"; Show-Help; exit 1 }
}
