<#
.SYNOPSIS
    Installs the TinyShell PowerShell module into the user's PowerShell module directory.
.PARAMETER Scope
    Installation scope: 'CurrentUser' (default) installs into Documents\PowerShell\Modules\TinyShell.
.PARAMETER Chord
    Default shortcut chord to configure in sample profile snippet. Default is 'Alt+s'.
#>
[CmdletBinding()]
param(
    [Parameter()]
    [ValidateSet('CurrentUser')]
    [string]$Scope = 'CurrentUser',

    [Parameter()]
    [string]$Chord = 'Alt+s'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$sourceModule = Join-Path $repoRoot "modules\TinyShell"

if (-not (Test-Path $sourceModule)) {
    throw "TinyShell module directory not found at $sourceModule. Please run scripts\publish_module.ps1 first."
}

# Determine destination module directory
$docsDir = [Environment]::GetFolderPath('MyDocuments')
if (-not $docsDir) {
    $docsDir = Join-Path $env:USERPROFILE "Documents"
}

$destBase = Join-Path $docsDir "PowerShell\Modules"
$destDir = Join-Path $destBase "TinyShell"

Write-Host "=== Installing TinyShell Module ===" -ForegroundColor Cyan
Write-Host "Source:      $sourceModule" -ForegroundColor DarkGray
Write-Host "Destination: $destDir" -ForegroundColor DarkGray

if (-not (Test-Path $destBase)) {
    New-Item -ItemType Directory -Path $destBase -Force | Out-Null
}

# Copy files
Copy-Item -Path $sourceModule -Destination $destBase -Recurse -Force

Write-Host "`nTinyShell installed successfully to: $destDir" -ForegroundColor Green
Write-Host "`nTo activate TinyShell in your current session:" -ForegroundColor Cyan
Write-Host "  Import-Module TinyShell" -ForegroundColor White
Write-Host "  Register-TinyIntentKeyHandler -Chord '$Chord'" -ForegroundColor White

Write-Host "`nTo enable TinyShell automatically in every PowerShell session, add to your `$PROFILE:" -ForegroundColor Cyan
Write-Host "  Import-Module TinyShell" -ForegroundColor Yellow
Write-Host "  Register-TinyIntentKeyHandler -Chord '$Chord'" -ForegroundColor Yellow
