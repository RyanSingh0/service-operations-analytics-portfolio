param([string]$AsOf = '', [int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Create .venv and install the project first; see README.md.'
}
if (-not (Test-Path -LiteralPath 'data\raw\incident_event_log.csv')) {
    & $pythonPath -m serviceops.cli download
    if ($LASTEXITCODE -ne 0) { throw 'Source download failed.' }
}
if (-not $AsOf) {
    if (Test-Path -LiteralPath 'build\incremental\committed.json') {
        $AsOf = (Get-Content -LiteralPath 'build\incremental\committed.json' -Raw | ConvertFrom-Json).as_of
    } else { $AsOf = '2016-05-01 23:59:59' }
}
& $pythonPath scripts/replay.py --as-of $AsOf
if ($LASTEXITCODE -ne 0) { throw 'Pipeline failed.' }
Write-Output "Dashboard: http://127.0.0.1:$Port"
& $pythonPath -m http.server $Port --bind 127.0.0.1 --directory build/incremental
