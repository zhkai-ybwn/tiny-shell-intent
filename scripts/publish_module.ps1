# Script to publish the standalone TinyShell PowerShell module

$ErrorActionPreference = 'Stop'
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$moduleDir = Join-Path $repoRoot "modules\TinyShell"

function Get-DotNetSdkCommand {
    $candidates = @()
    $userDotnet = Join-Path $env:USERPROFILE ".dotnet\dotnet.exe"
    if (Test-Path $userDotnet) { $candidates += $userDotnet }

    $pathDotnet = (Get-Command dotnet -ErrorAction SilentlyContinue)?.Source
    if ($pathDotnet -and -not ($candidates -contains $pathDotnet)) { $candidates += $pathDotnet }

    $pfDotnet = "C:\Program Files\dotnet\dotnet.exe"
    if ((Test-Path $pfDotnet) -and -not ($candidates -contains $pfDotnet)) { $candidates += $pfDotnet }

    foreach ($cmd in $candidates) {
        try {
            $sdks = & $cmd --list-sdks 2>$null
            if ($sdks -and ($sdks -match '\d+\.\d+')) {
                return $cmd
            }
        } catch { }
    }
    throw "No working .NET SDK command found. Please ensure .NET SDK 8.0+ is installed."
}

$dotnetCmd = Get-DotNetSdkCommand
Write-Host "Building TinyShell in Release configuration using $dotnetCmd..." -ForegroundColor Cyan
& $dotnetCmd build (Join-Path $repoRoot "src\TinyShell.PowerShell\TinyShell.PowerShell.csproj") -c Release
if ($LASTEXITCODE -ne 0) {
    throw "TinyShell build failed with exit code $LASTEXITCODE. Module publishing aborted."
}

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
