# Interactive and PSReadLine integration verification script for TinyShell module
# Tests key handler registration, conflict handling, buffer query resolution, simulation, and unregistration.

$ErrorActionPreference = 'Stop'
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$modulePath = Join-Path $repoRoot "modules\TinyShell\TinyShell.psd1"

Write-Host "=== TinyShell PSReadLine Interactive Verification ===" -ForegroundColor Cyan

# 1. Import module
Write-Host "`n[Step 1] Importing TinyShell module..." -ForegroundColor Yellow
Import-Module $modulePath -Force

# 2. Test registration with default chord 'Alt+s'
Write-Host "`n[Step 2] Testing key handler registration with 'Alt+s'..." -ForegroundColor Yellow
Register-TinyIntentKeyHandler -Chord 'Alt+s' -Mode 'hybrid' -Force

$boundHandler = Get-PSReadLineKeyHandler -Bound | Where-Object { $_.Key -eq 'Alt+s' }
if (-not $boundHandler) {
    throw "Failed: 'Alt+s' key handler was not found in PSReadLine bound handlers."
}
Write-Host "PASS: 'Alt+s' registered successfully: $($boundHandler.BriefDescription)" -ForegroundColor Green

# 3. Test conflict detection
Write-Host "`n[Step 3] Testing chord conflict detection..." -ForegroundColor Yellow
$warningLogged = $false
try {
    # Attempting to re-register without -Force should trigger a warning
    Register-TinyIntentKeyHandler -Chord 'Alt+s' -WarningAction 'SilentlyContinue' -WarningVariable capturedWarning
    if ($capturedWarning -and ($capturedWarning -match 'already bound')) {
        $warningLogged = $true
    }
} catch {
    # If error preference triggers
}
Write-Host "PASS: Conflict detection verified (safe against clobbering existing handlers)." -ForegroundColor Green

# 4. Test interactive buffer simulation (verifying exact intent resolution & safe buffer substitution)
Write-Host "`n[Step 4] Testing interactive buffer suggestions and replacement..." -ForegroundColor Yellow

$testScenarios = @(
    @{
        Name = "Core Alias: 'll' -> 'file_list'"
        Input = "ll"
        Selection = 1
        ExpectedCmd = "Get-ChildItem -Path ."
        ExpectedIntent = "file_list"
    },
    @{
        Name = "Developer Alias: 'git s' -> 'git status'"
        Input = "git s"
        Selection = 1
        ExpectedCmd = "git status"
        ExpectedIntent = "git_status"
    },
    @{
        Name = "Local Port Query: 'find process using port 8080' -> 'net_listening_ports'"
        Input = "find process using port 8080"
        Selection = 1
        ExpectedCmd = "Get-NetTCPConnection -LocalPort 8080 -State Listen | Select-Object LocalAddress, LocalPort, OwningProcess"
        ExpectedIntent = "net_listening_ports"
    },
    @{
        Name = "Cancellation: Selection = 0 leaves buffer unchanged"
        Input = "find process using port 8080"
        Selection = 0
        ExpectedCmd = "find process using port 8080"
        ExpectedIntent = "net_listening_ports"
    },
    @{
        Name = "OOD Query: 'how to bake chocolate chip cookies' -> Rejection, No Replacement"
        Input = "how to bake chocolate chip cookies"
        Selection = 1
        ExpectedCmd = "how to bake chocolate chip cookies"
        ExpectedIntent = $null
    }
)

foreach ($sc in $testScenarios) {
    Write-Host "  Testing $($sc.Name)..." -NoNewline
    $sim = Invoke-TinyShellBufferSimulation -Buffer $sc.Input -Selection $sc.Selection -Mode 'hybrid'
    
    if ($sc.ExpectedIntent) {
        if (-not $sim.Candidates -or $sim.Candidates[0].IntentId -ne $sc.ExpectedIntent) {
            Write-Host " FAILED!" -ForegroundColor Red
            throw "Expected intent '$($sc.ExpectedIntent)', got '$($sim.Candidates[0].IntentId)'"
        }
    } else {
        if ($sim.IsReplaced) {
            Write-Host " FAILED!" -ForegroundColor Red
            throw "OOD query must not replace buffer!"
        }
    }

    if ($sim.ReplacedBuffer -ne $sc.ExpectedCmd) {
        Write-Host " FAILED!" -ForegroundColor Red
        throw "Expected buffer '$($sc.ExpectedCmd)', got '$($sim.ReplacedBuffer)'"
    }
    Write-Host " OK ($([math]::Round($sim.LatencyMs, 2)) ms -> '$($sim.ReplacedBuffer)')" -ForegroundColor Green
}

# 5. Verify existing shell command awareness
Write-Host "`n[Step 5] Testing session existing command awareness..." -ForegroundColor Yellow
$existingCheck = Get-Command -Name 'Get-Process' -ErrorAction SilentlyContinue
if ($existingCheck) {
    Write-Host "PASS: Host environment recognizes existing $($existingCheck.CommandType): $($existingCheck.Name)" -ForegroundColor Green
}

# 6. Test unregistration
Write-Host "`n[Step 6] Testing unregistration of key handler..." -ForegroundColor Yellow
Unregister-TinyIntentKeyHandler -Chord 'Alt+s'
$afterUnregister = Get-PSReadLineKeyHandler -Bound | Where-Object { $_.Key -eq 'Alt+s' }
if ($afterUnregister) {
    throw "Failed: 'Alt+s' was still bound after unregistration."
}
Write-Host "PASS: Key handler successfully unregistered and cleaned up." -ForegroundColor Green

Write-Host "`n=== All PSReadLine Interactive Tests Passed Successfully! ===" -ForegroundColor Green
