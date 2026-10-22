# TinyShell PowerShell Module
# Offline semantic intent recommendation plugin for PowerShell 7.4+

$moduleRoot = $PSScriptRoot

# Configure paths in TinyShellSession
$coreDll = Join-Path $moduleRoot "TinyShell.Core.dll"
$psDll = Join-Path $moduleRoot "TinyShell.PowerShell.dll"

if (Test-Path $coreDll) {
    Add-Type -Path $coreDll -ErrorAction SilentlyContinue
}
if (Test-Path $psDll) {
    Add-Type -Path $psDll -ErrorAction SilentlyContinue
}

# Set default model and KB paths
$kbFile = Join-Path $moduleRoot "data\knowledge_base.json"
if (-not (Test-Path $kbFile)) {
    $kbFile = Join-Path $moduleRoot "..\..\data\knowledge_base.json"
}

$modelDir = Join-Path $moduleRoot "models\potion-base-2M"
if (-not (Test-Path $modelDir)) {
    $modelDir = Join-Path $moduleRoot "..\..\models\potion-base-2M"
}

if (Test-Path $kbFile) {
    [TinyShell.PowerShell.TinyShellSession]::DefaultKbPath = (Resolve-Path $kbFile).Path
}
if (Test-Path $modelDir) {
    [TinyShell.PowerShell.TinyShellSession]::DefaultModelPath = (Resolve-Path $modelDir).Path
}

# Script-scoped state
$script:TinyShellMode = 'hybrid'
$script:TinyShellChord = 'Alt+s'

<#
.SYNOPSIS
    Registers an interactive PSReadLine key handler for TinyShell command suggestions.
.PARAMETER Chord
    Key combination to trigger suggestion menu. Default is 'Alt+s' (avoids Tab / Ctrl+I collision).
.PARAMETER Mode
    Retrieval mode: 'hybrid', 'rule', 'fuzzy', 'model'. Default is 'hybrid'.
.PARAMETER Force
    Force binding even if the chord is already bound to another PSReadLine function.
#>
function Register-TinyIntentKeyHandler {
    [CmdletBinding()]
    param(
        [Parameter()]
        [string]$Chord = 'Alt+s',

        [Parameter()]
        [ValidateSet('hybrid', 'rule', 'fuzzy', 'model')]
        [string]$Mode = 'hybrid',

        [Parameter()]
        [switch]$Force
    )

    if (-not (Get-Module -Name 'PSReadLine')) {
        Write-Warning "PSReadLine module is not loaded. Interactive key handler requires PSReadLine."
        return
    }

    # Detect conflicts with existing key bindings
    $existingBinding = Get-PSReadLineKeyHandler -Bound | Where-Object { $_.Key -eq $Chord }
    if ($existingBinding -and -not $Force) {
        Write-Warning "[TinyShell] Key chord '$Chord' is already bound to function '$($existingBinding.Function)'. Pass -Force to override or select another chord with -Chord."
        return
    }

    # Persist configuration in module-scope variables
    $script:TinyShellMode = $Mode
    $script:TinyShellChord = $Chord

    Set-PSReadLineKeyHandler -Chord $Chord -BriefDescription "TinyShell Semantic Suggestion" -LongDescription "Suggests PowerShell commands using offline semantic intent matching." -ScriptBlock {
        param($key, $arg)

        $line = $null
        $cursor = $null
        [Microsoft.PowerShell.PSConsoleReadLine]::GetBufferState([ref]$line, [ref]$cursor)

        if ([string]::IsNullOrWhiteSpace($line)) {
            return
        }

        $cleanLine = $line.Trim()
        $tokens = $cleanLine -split '\s+'
        $firstToken = if ($tokens.Count -gt 0) { $tokens[0] } else { "" }

        # Check if the command is already a valid command or alias in the current shell
        $existingCmd = $null
        if ($firstToken) {
            $existingCmd = Get-Command -Name $firstToken -ErrorAction SilentlyContinue
        }

        # Retrieve mode from persistent module scope
        $currentMode = if ($script:TinyShellMode) { $script:TinyShellMode } else { 'hybrid' }

        # Query IntentEngine
        $res = Get-TinyIntent -Query $cleanLine -Top 3 -Mode $currentMode

        if (-not $res.IsAccepted -or $res.Candidates.Count -eq 0) {
            Write-Host "`n[TinyShell] No matching intent recognized ($($res.RejectionReason))." -ForegroundColor DarkGray
            [Microsoft.PowerShell.PSConsoleReadLine]::Repaint()
            return
        }

        # Render Interactive Suggestion Box
        Write-Host ""
        $latencyDisplay = [math]::Round($res.LatencyMs, 2)
        Write-Host "╭── TinyShell Suggestions ($($res.Candidates.Count) matches in ${latencyDisplay} ms) ──────────────────────────" -ForegroundColor Cyan

        if ($existingCmd) {
            Write-Host " │ " -NoNewline -ForegroundColor Cyan
            Write-Host "ℹ Note: '$firstToken' is an existing $($existingCmd.CommandType) in your session." -ForegroundColor Yellow
        }

        $idx = 1
        foreach ($cand in $res.Candidates) {
            $riskColor = switch ($cand.RiskLevel) {
                "safe" { "Green" }
                "warning" { "Yellow" }
                "dangerous" { "Red" }
                default { "Gray" }
            }
            $riskBadge = "[$($cand.RiskLevel.ToUpper())]"
            $completeBadge = if ($cand.IsComplete) { "" } else { " [NEEDS PARAMS]" }
            $cmdText = if ($cand.RenderedCommand) { $cand.RenderedCommand } else { $cand.Command }

            Write-Host " │ " -NoNewline -ForegroundColor Cyan
            Write-Host "[$idx] " -NoNewline -ForegroundColor White
            Write-Host "$cmdText" -NoNewline -ForegroundColor Green
            Write-Host " $riskBadge" -NoNewline -ForegroundColor $riskColor
            if ($completeBadge) {
                Write-Host "$completeBadge" -NoNewline -ForegroundColor DarkYellow
            }
            Write-Host ""

            Write-Host " │     " -NoNewline -ForegroundColor Cyan
            Write-Host "$($cand.Description) ($($cand.Source): $($cand.Score))" -ForegroundColor DarkGray
            $idx++
        }
        Write-Host "╰──────────────────────────────────────────────────────────────────────────" -ForegroundColor Cyan

        if ([Console]::IsInputRedirected) {
            [Microsoft.PowerShell.PSConsoleReadLine]::Repaint()
            return
        }

        # User choice: 1, 2, 3 or Esc/Enter to cancel
        Write-Host "Select [1-$($res.Candidates.Count)], or [Esc/Enter] keep original: " -NoNewline -ForegroundColor Cyan
        $keyPress = [Console]::ReadKey($true)
        Write-Host ""

        $selectedCmd = $null
        if ($keyPress.KeyChar -eq '1' -and $res.Candidates.Count -ge 1) {
            $selectedCmd = if ($res.Candidates[0].RenderedCommand) { $res.Candidates[0].RenderedCommand } else { $res.Candidates[0].Command }
        }
        elseif ($keyPress.KeyChar -eq '2' -and $res.Candidates.Count -ge 2) {
            $selectedCmd = if ($res.Candidates[1].RenderedCommand) { $res.Candidates[1].RenderedCommand } else { $res.Candidates[1].Command }
        }
        elseif ($keyPress.KeyChar -eq '3' -and $res.Candidates.Count -ge 3) {
            $selectedCmd = if ($res.Candidates[2].RenderedCommand) { $res.Candidates[2].RenderedCommand } else { $res.Candidates[2].Command }
        }

        if ($selectedCmd) {
            # SAFETY GUARANTEE: Replace buffer only, NEVER call AcceptLine() / auto-execute!
            [Microsoft.PowerShell.PSConsoleReadLine]::Replace(0, $line.Length, $selectedCmd)
        }
        else {
            [Microsoft.PowerShell.PSConsoleReadLine]::Repaint()
        }
    }

    Write-Host "[TinyShell] Key handler registered for chord: '$Chord' (Mode: $Mode)" -ForegroundColor Cyan
}

<#
.SYNOPSIS
    Unregisters the TinyShell PSReadLine key handler.
.PARAMETER Chord
    Key combination to unregister. Default is the currently registered chord.
#>
function Unregister-TinyIntentKeyHandler {
    [CmdletBinding()]
    param(
        [Parameter()]
        [string]$Chord = $script:TinyShellChord
    )

    if (Get-Module -Name 'PSReadLine') {
        Remove-PSReadLineKeyHandler -Chord $Chord -ErrorAction SilentlyContinue
        Write-Host "[TinyShell] Unregistered key handler for chord: '$Chord'" -ForegroundColor DarkGray
    }
}

<#
.SYNOPSIS
    Simulates buffer suggestion and replacement for testing without physical keyboard hardware.
.PARAMETER Buffer
    Simulated command line input buffer.
.PARAMETER Selection
    Selected candidate index (1, 2, 3), or 0 / $null to cancel.
.PARAMETER Mode
    Retrieval mode ('hybrid', 'rule', 'fuzzy', 'model').
#>
function Invoke-TinyShellBufferSimulation {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Buffer,

        [Parameter()]
        [int]$Selection = 1,

        [Parameter()]
        [string]$Mode = 'hybrid'
    )

    $cleanLine = $Buffer.Trim()
    if ([string]::IsNullOrWhiteSpace($cleanLine)) {
        return [PSCustomObject]@{
            OriginalBuffer = $Buffer
            ReplacedBuffer = $Buffer
            IsReplaced = $false
            Candidates = @()
        }
    }

    $res = Get-TinyIntent -Query $cleanLine -Top 3 -Mode $Mode
    if (-not $res.IsAccepted -or $res.Candidates.Count -eq 0) {
        return [PSCustomObject]@{
            OriginalBuffer = $Buffer
            ReplacedBuffer = $Buffer
            IsReplaced = $false
            RejectionReason = $res.RejectionReason
            Candidates = @()
        }
    }

    $selectedCmd = $null
    if ($Selection -ge 1 -and $Selection -le $res.Candidates.Count) {
        $cand = $res.Candidates[$Selection - 1]
        $selectedCmd = if ($cand.RenderedCommand) { $cand.RenderedCommand } else { $cand.Command }
    }

    return [PSCustomObject]@{
        OriginalBuffer = $Buffer
        ReplacedBuffer = if ($selectedCmd) { $selectedCmd } else { $Buffer }
        IsReplaced = [bool]$selectedCmd
        SelectedCommand = $selectedCmd
        Candidates = $res.Candidates
        LatencyMs = $res.LatencyMs
    }
}

Export-ModuleMember -Cmdlet Get-TinyIntent, Initialize-TinyIntent -Function Register-TinyIntentKeyHandler, Unregister-TinyIntentKeyHandler, Invoke-TinyShellBufferSimulation
