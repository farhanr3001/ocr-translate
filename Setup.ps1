$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    py -3.10 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.10 x64 is required for development.' }
}
& .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
Write-Host 'Ready. Open Launch.cmd to start Arabic Lens.'
