Import-Module ./modules/TinyShell/TinyShell.psd1 -Force

Write-Host "=== TinyShell Cmdlet Verification in PowerShell 7 ===" -ForegroundColor Cyan

function Run-Scenario($num, $title, $query) {
    Write-Host "`n[$num] Scenario: $title" -ForegroundColor Yellow
    Write-Host "Query: '$query'" -ForegroundColor DarkGray
    $res = Get-TinyIntent -Query $query
    Write-Host "Result: Accepted=$($res.IsAccepted), Rejected=$($res.IsRejected), OOD=$($res.IsOutOfDomain), Latency=$([math]::Round($res.LatencyMs, 2))ms"

    if ($res.Candidates.Count -gt 0) {
        $res.Candidates | Format-Table -Property IntentId, Command, Score, Source, RiskLevel, IsComplete -AutoSize
    }
    elseif ($res.DebugCandidates.Count -gt 0) {
        Write-Host "Debug Candidates (Rejected Reason: $($res.RejectionReason)):" -ForegroundColor DarkYellow
        $res.DebugCandidates | Format-Table -Property IntentId, Command, Score, Source -AutoSize
    }
    else {
        Write-Host "Rejection: $($res.RejectionReason)" -ForegroundColor Red
    }
}

Run-Scenario 1 "Alias resolution" "ll"
Run-Scenario 2 "Exact alias short-circuit" "pwd"
Run-Scenario 3 "Existing command check" "Get-Process"
Run-Scenario 4 "Typo tolerance" "get-childiitem"
Run-Scenario 5 "Parameter extraction" "find process using port 8080"
Run-Scenario 6 "External CLI tool rejection" "git status"
Run-Scenario 7 "Risk & parameter extraction" "kill process 12480 immediately"
Run-Scenario 8 "Out-of-domain rejection" "def fibonacci(n): return n"
