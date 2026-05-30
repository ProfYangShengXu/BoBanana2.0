<#
.SYNOPSIS
  Build a portable zip package for distribution.

  Creates dist\BoBanana2.0-portable.zip with a single top-level BoBanana2.0\ folder
  that always includes install.cmd / install.py / INSTALL.md at the folder root.

.USAGE
  .\pack.ps1
  .\pack.ps1 -OutputDir D:\out
#>

[CmdletBinding()]
param(
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Dist = if ($OutputDir) { $OutputDir } else { Join-Path $Root "dist" }
$ZipName = "BoBanana2.0-portable.zip"
$ZipPath = Join-Path $Dist $ZipName
$Stage = Join-Path $Dist "BoBanana2.0"

$ExcludeDirNames = @(
    ".venv", "venv", ".bobanana", ".git", "__pycache__", "dist", ".cursor", "node_modules", ".pytest_cache"
)

$ExcludeRelPrefixes = @(
    "docs\delivery\output\",
    "critique_report.md",
    "config_files_summary.md",
    "diagnostic_files_summary.md",
    "_matches.txt",
    "matches_out.txt",
    "test_write.txt",
    "langgraph_latest_",
    "pypi_langgraph.json"
)

$MustHaveAtRoot = @(
    "install.cmd", "install.ps1", "install.py", "install.sh",
    "bb.cmd", "bb.ps1", "bb.sh",
    ".env.example", "requirements.txt", "INSTALL.md", "START-HERE.txt"
)

$MustHaveSkills = @(
    "code-delivery-gate",
    "agent-reach"
)

function Should-Skip([string]$FullPath) {
    $rel = $FullPath.Substring($Root.Length).TrimStart("\")
    foreach ($part in $rel.Split("\")) {
        if ($ExcludeDirNames -contains $part) { return $true }
    }
    $name = Split-Path $FullPath -Leaf
    foreach ($pat in $ExcludeFileNames) {
        if ($name -like $pat) { return $true }
    }
    $relNorm = $rel -replace "/", "\"
    foreach ($prefix in $ExcludeRelPrefixes) {
        if ($relNorm -like "$prefix*") { return $true }
    }
    return $false
}

Write-Host "[pack] staging portable bundle ..." -ForegroundColor Cyan
if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force }
New-Item -ItemType Directory -Path $Stage -Force | Out-Null

Get-ChildItem $Root -Recurse -File | ForEach-Object {
    if (Should-Skip $_.FullName) { return }
    $rel = $_.FullName.Substring($Root.Length).TrimStart("\")
    $dest = Join-Path $Stage $rel
    $destDir = Split-Path $dest -Parent
    if (-not (Test-Path $destDir)) { New-Item -ItemType Directory -Path $destDir -Force | Out-Null }
    Copy-Item $_.FullName $dest -Force
}

# Bundled skills (workspace/skills is auto-scanned by SkillRegistry).
$skillsSrc = Join-Path $Root "skills"
if (-not (Test-Path $skillsSrc)) {
    $bundleScript = Join-Path $Root "scripts\bundle-skills.ps1"
    if (Test-Path $bundleScript) {
        Write-Host "[pack] skills/ missing — running bundle-skills.ps1 ..." -ForegroundColor Yellow
        & powershell -NoProfile -ExecutionPolicy Bypass -File $bundleScript
    }
}
if (-not (Test-Path $skillsSrc)) {
    throw "pack failed: skills/ not found. Run scripts\bundle-skills.ps1 first."
}
Write-Host "[pack] skills/ bundle present" -ForegroundColor Cyan

foreach ($sk in $MustHaveSkills) {
    $skillMd = Join-Path $Stage "skills\$sk\SKILL.md"
    if (-not (Test-Path $skillMd)) {
        throw "pack validation failed: missing skills\$sk\SKILL.md"
    }
}

# Chinese install alias (same as install.cmd).
$cnInstall = Join-Path $Stage ([char]0x5B89 + [char]0x88C5 + ".cmd")
Copy-Item (Join-Path $Root "install.cmd") $cnInstall -Force

$startHere = @"
BoBanana 2.0 - START HERE
=========================

Windows:
  1. Unzip anywhere, open the BoBanana2.0 folder
  2. Double-click install.cmd (or the Chinese-named install shortcut)
  3. Enter API key when asked, or skip and run: bb config
  4. Use desktop shortcut BoBanana 2.0

Bundled skills (in skills/ folder, no extra setup):
  code-delivery-gate, agent-reach
  In agent: /skills to list them.

macOS / Linux:
  chmod +x install.sh bb.sh
  ./install.sh

Full guide: INSTALL.md
"@
Set-Content (Join-Path $Stage "START-HERE.txt") -Value $startHere -Encoding UTF8

foreach ($must in $MustHaveAtRoot) {
    if (-not (Test-Path (Join-Path $Stage $must))) {
        throw "pack validation failed: missing $must in stage"
    }
}
if (-not (Test-Path $cnInstall)) {
    throw "pack validation failed: missing Chinese install.cmd alias"
}

New-Item -ItemType Directory -Path $Dist -Force | Out-Null
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }

Compress-Archive -Path $Stage -DestinationPath $ZipPath -Force
Remove-Item $Stage -Recurse -Force

Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [IO.Compression.ZipFile]::OpenRead($ZipPath)
$verify = @("install.cmd", "install.py", "INSTALL.md", "START-HERE.txt")
$found = @()
foreach ($must in $verify) {
    $hit = @($zip.Entries | Where-Object { $_.FullName -like "*$must" })
    if ($hit.Count -gt 0) { $found += $must }
    else { Write-Host "[pack] WARN: missing $must in zip" -ForegroundColor Red }
}
$zip.Dispose()

if ($found.Count -lt $verify.Count) {
    throw "pack verification failed: install entry points missing from zip"
}

$sizeMb = [math]::Round((Get-Item $ZipPath).Length / 1MB, 2)
Write-Host ("[pack] created: {0} ({1} MB)" -f $ZipPath, $sizeMb) -ForegroundColor Green
Write-Host ("[pack] verified in zip: {0}" -f ($found -join ", ")) -ForegroundColor Green
Write-Host "[pack] extract zip -> open BoBanana2.0 folder -> double-click install.cmd" -ForegroundColor Gray
