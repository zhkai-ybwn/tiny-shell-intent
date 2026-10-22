# Quick installer entrypoint for TinyShell
param(
    [string]$Chord = 'Alt+s'
)
& (Join-Path $PSScriptRoot "scripts\Install-TinyShell.ps1") -Chord $Chord
