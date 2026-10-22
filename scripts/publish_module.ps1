# Script to publish the standalone TinyShell PowerShell module

$ErrorActionPreference = 'Stop'
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$moduleDir = Join-Path $repoRoot "modules\TinyShell"

Write-Host "Building TinyShell in Release configuration..." -ForegroundColor Cyan
& "C:\Users\user\.dotnet\dotnet.exe" build (Join-Path $repoRoot "src\TinyShell.PowerShell\TinyShell.PowerShell.csproj") -c Release

$releaseBin = Join-Path $repoRoot "src\TinyShell.PowerShell\bin\Release\net8.0"

# Create directories in module directory
New-Item -ItemType Directory -Path (Join-Path $moduleDir "data") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $moduleDir "models\potion-base-2M") -Force | Out-Null

Write-Host "Copying binaries and data..." -ForegroundColor Cyan
Copy-Item (Join-Path $releaseBin "TinyShell.PowerShell.dll") $moduleDir -Force
Copy-Item (Join-Path $releaseBin "TinyShell.Core.dll") $moduleDir -Force
Copy-Item (Join-Path $repoRoot "data\knowledge_base.json") (Join-Path $moduleDir "data\knowledge_base.json") -Force
Copy-Item (Join-Path $repoRoot "models\potion-base-2M\model.safetensors") (Join-Path $moduleDir "models\potion-base-2M\model.safetensors") -Force
Copy-Item (Join-Path $repoRoot "models\potion-base-2M\tokenizer.json") (Join-Path $moduleDir "models\potion-base-2M\tokenizer.json") -Force

# Calculate module folder size
$files = Get-ChildItem -Path $moduleDir -Recurse -File
$totalBytes = ($files | Measure-Object -Property Length -Sum).Sum
$totalMb = [math]::Round($totalBytes / 1MB, 2)

Write-Host "TinyShell module published successfully to: $moduleDir" -ForegroundColor Green
Write-Host "Total Module Package Size: $totalMb MB ($totalBytes bytes)" -ForegroundColor Green

Write-Host "`nBreakdown:" -ForegroundColor Cyan
foreach ($f in $files) {
    $rel = $f.FullName.Substring($moduleDir.Path.Length + 1)
    $sizeKb = [math]::Round($f.Length / 1KB, 1)
    Write-Host "  $rel ($sizeKb KB)" -ForegroundColor DarkGray
}
