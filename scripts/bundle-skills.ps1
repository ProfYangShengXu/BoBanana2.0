<#
.SYNOPSIS
  Copy local Cursor/Agent skills into the portable package skills/ folder.

.USAGE
  .\scripts\bundle-skills.ps1
  .\scripts\bundle-skills.ps1 -SourceDir "$env:USERPROFILE\.cursor\skills"
#>

[CmdletBinding()]
param(
    [string]$SourceDir = "",
    [string]$DestDir = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Dest = if ($DestDir) { $DestDir } else { Join-Path $Root "skills" }

$sources = @()
if ($SourceDir) {
    $sources += $SourceDir
} else {
    $sources += @(
        (Join-Path $env:USERPROFILE ".cursor\skills"),
        (Join-Path $env:USERPROFILE ".agents\skills")
    )
}

$DefaultSkills = @(
    "code-delivery-gate",
    "agent-reach"
)

if (Test-Path $Dest) { Remove-Item $Dest -Recurse -Force }
New-Item -ItemType Directory -Path $Dest -Force | Out-Null

$copied = 0
foreach ($base in $sources) {
    if (-not (Test-Path $base)) { continue }
    foreach ($name in $DefaultSkills) {
        $src = Join-Path $base $name
        if (-not (Test-Path $src)) { continue }
        $dst = Join-Path $Dest $name
        if (Test-Path $dst) { continue }
        Copy-Item $src $dst -Recurse -Force
        if (Test-Path (Join-Path $dst "SKILL.md")) {
            Write-Host "[bundle-skills] $name <- $src" -ForegroundColor Green
            $copied++
        }
    }
}

if ($copied -eq 0) {
    throw "no skills copied — check .cursor/skills or pass -SourceDir"
}

Write-Host "[bundle-skills] done: $copied skill(s) in $Dest" -ForegroundColor Cyan
