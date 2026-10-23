# Parser and publishing regressions. Never executes any suggested command.
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$coreDll = Join-Path $repoRoot 'src/TinyShell.Core/bin/Debug/net8.0/TinyShell.Core.dll'
if (-not (Test-Path -LiteralPath $coreDll)) {
    throw 'Build the C# test project before running this script.'
}
Add-Type -Path $coreDll
$engine = [TinyShell.Core.IntentEngine]::new(
    (Join-Path $repoRoot 'data/knowledge_base.json'),
    (Join-Path $repoRoot 'models/potion-base-2M'))

foreach ($query in @('check env PATH', 'check env NODE_ENV', 'set NODE_ENV to production', 'delete file "C:\My Documents\report.txt"')) {
    $result = $engine.Search($query)
    $candidate = $result.TopCandidate
    if (-not $result.IsAccepted -or -not $candidate.IsComplete) {
        throw "Expected a complete candidate: $query"
    }
    $parseTokens = $null
    $parseErrors = $null
    $null = [System.Management.Automation.Language.Parser]::ParseInput(
        $candidate.Command, [ref]$parseTokens, [ref]$parseErrors)
    if ($parseErrors.Count) { throw "Invalid generated syntax: $($candidate.Command)" }
}
Write-Host 'PASS: Complete file and environment suggestions parse as PowerShell.'

foreach ($quote in @([char]0x2018, [char]0x2019, [char]0x201a, [char]0x201b)) {
    $query = 'delete file ' + [char]39 + 'C:\review' + $quote +
        ' -Recurse -ErrorAction ' + $quote + 'SilentlyContinue' + [char]39
    $candidate = $engine.Search($query).TopCandidate
    if ($candidate.IsComplete -or $candidate.RenderedCommand) {
        throw 'Smart quote payload produced a complete command.'
    }
}
Write-Host 'PASS: Smart quote payloads cannot produce complete commands.'

# Use a real failed build in an isolated repository, with stale binaries present.
$tempParent = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$fixtureRoot = Join-Path $tempParent ('TinyShell-Review-' + [guid]::NewGuid().ToString('N'))
try {
    $fixtureScripts = Join-Path $fixtureRoot 'scripts'
    $fixtureProject = Join-Path $fixtureRoot 'src/TinyShell.PowerShell'
    $fixtureModule = Join-Path $fixtureRoot 'modules/TinyShell'
    $fixtureRelease = Join-Path $fixtureProject 'bin/Release/net8.0'
    foreach ($directory in @($fixtureScripts, $fixtureProject, $fixtureModule, $fixtureRelease)) {
        $null = New-Item -ItemType Directory -Path $directory -Force
    }
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'publish_module.ps1') -Destination $fixtureScripts
    Set-Content -LiteralPath (Join-Path $fixtureProject 'TinyShell.PowerShell.csproj') -Value '<Project><Invalid' -Encoding utf8
    foreach ($name in @('TinyShell.Core.dll', 'TinyShell.PowerShell.dll')) {
        Set-Content -LiteralPath (Join-Path $fixtureRelease $name) -Value 'STALE BUILD' -Encoding utf8
        Set-Content -LiteralPath (Join-Path $fixtureModule $name) -Value 'KEEP EXISTING MODULE' -Encoding utf8
    }
    # Supply all later copy sources so an unguarded script would incorrectly succeed.
    $null = New-Item -ItemType Directory -Path (Join-Path $fixtureRoot 'data') -Force
    $null = New-Item -ItemType Directory -Path (Join-Path $fixtureRoot 'models/potion-base-2M') -Force
    Set-Content -LiteralPath (Join-Path $fixtureRoot 'data/knowledge_base.json') -Value '[]'
    foreach ($name in @('model.safetensors', 'tokenizer.json')) {
        Set-Content -LiteralPath (Join-Path $fixtureRoot "models/potion-base-2M/$name") -Value 'FIXTURE'
    }
    $output = & (Join-Path $PSHOME 'pwsh.exe') -NoProfile -File (Join-Path $fixtureScripts 'publish_module.ps1') 2>&1
    $publishExitCode = $LASTEXITCODE
    if ($publishExitCode -eq 0 -or ($output -join "`n") -notmatch 'Module publishing aborted') {
        throw "Failed build was not explicitly aborted: $output"
    }
    foreach ($name in @('TinyShell.Core.dll', 'TinyShell.PowerShell.dll')) {
        if ((Get-Content -LiteralPath (Join-Path $fixtureModule $name) -Raw).Trim() -ne 'KEEP EXISTING MODULE') {
            throw 'Failed build overwrote existing module binaries.'
        }
    }
    if (Test-Path -LiteralPath (Join-Path $fixtureModule 'data')) {
        throw 'Failed build reached the resource copy stage.'
    }
    Write-Host 'PASS: Failed build aborts publishing and preserves existing module files.'
}
finally {
    # Resolve and check the exact temporary target before recursive cleanup.
    if (Test-Path -LiteralPath $fixtureRoot) {
        $resolvedFixture = (Resolve-Path -LiteralPath $fixtureRoot).Path
        $resolvedParent = [IO.Path]::GetFullPath((Split-Path -Parent $resolvedFixture))
        if ($resolvedParent.TrimEnd('\') -ne $tempParent.TrimEnd('\') -or
            (Split-Path -Leaf $resolvedFixture) -notmatch '^TinyShell-Review-[0-9a-f]{32}$') {
            throw "Refusing to clean unexpected fixture path: $resolvedFixture"
        }
        Remove-Item -LiteralPath $resolvedFixture -Recurse -Force
    }
}
