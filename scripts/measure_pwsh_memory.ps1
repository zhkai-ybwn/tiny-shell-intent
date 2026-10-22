# Measure actual process WorkingSet64 in a clean pwsh session

$proc = Get-Process -Id $PID
[GC]::Collect()
[GC]::WaitForPendingFinalizers()
[GC]::Collect()
$memBefore = $proc.WorkingSet64 / 1MB

Import-Module ./modules/TinyShell/TinyShell.psd1 -Force
# Warm up engine and load model
$res = Get-TinyIntent -Query "find process using port 8080"

[GC]::Collect()
[GC]::WaitForPendingFinalizers()
[GC]::Collect()
$proc.Refresh()
$memAfter = $proc.WorkingSet64 / 1MB
$delta = [math]::Round($memAfter - $memBefore, 2)

Write-Host "PowerShell 7 PID: $PID" -ForegroundColor Cyan
Write-Host "Initial WorkingSet64: $([math]::Round($memBefore, 2)) MB" -ForegroundColor DarkGray
Write-Host "After TinyShell loaded: $([math]::Round($memAfter, 2)) MB" -ForegroundColor DarkGray
Write-Host "Incremental Resident Memory: $delta MB" -ForegroundColor Green
