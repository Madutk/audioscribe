<#
.SYNOPSIS
    Startet die AudioScribe-Oberflaeche unter Windows mit allen Extras (review, agent, live).

.DESCRIPTION
    'uv run' gleicht die Umgebung vor dem Start ab - fehlende Pakete (PyAudioWPatch, mss, ...)
    werden dabei nachinstalliert. Ohne NVIDIA-Karte kommen die schlanken CPU-Wheels von torch.
    Nur ASCII in dieser Datei: Windows PowerShell 5.1 liest UTF-8 ohne BOM falsch.

.PARAMETER Torch
    auto (Default: cu124, wenn nvidia-smi eine Karte meldet, sonst cpu) | cpu | cu124

.PARAMETER Port
    HTTP-Port der Oberflaeche (Default: 8766)

.PARAMETER NoBrowser
    Browser nicht automatisch oeffnen

.EXAMPLE
    .\start.ps1
    .\start.ps1 -Torch cpu -Port 8800 -NoBrowser
#>
param(
    [ValidateSet('auto', 'cpu', 'cu124')]
    [string]$Torch = 'auto',
    [int]$Port = 8766,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "uv fehlt -> winget install astral-sh.uv"
}

if ($Torch -eq 'auto') {
    $Torch = 'cpu'
    if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
        & nvidia-smi -L *> $null
        if ($LASTEXITCODE -eq 0) { $Torch = 'cu124' }
    }
}

$uiArgs = @('ui', '--port', $Port)
if ($NoBrowser) { $uiArgs += '--no-browser' }

Write-Host "AudioScribe: torch=$Torch, Extras review/agent/live, Port $Port (beenden mit Strg+C)"
& uv run --extra $Torch --extra review --extra agent --extra live audioscribe @uiArgs
exit $LASTEXITCODE
