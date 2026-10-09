$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& .\.venv\Scripts\python.exe tools\make_icon.py
if ($LASTEXITCODE -ne 0) { throw 'Icon creation failed.' }
& .\.venv\Scripts\python.exe tools\build.py
if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
Copy-Item -LiteralPath 'README.md' -Destination 'dist\ArabicLens\README.md'
Copy-Item -LiteralPath 'THIRD_PARTY.md' -Destination 'dist\ArabicLens\THIRD_PARTY.md'
Compress-Archive -LiteralPath 'dist\ArabicLens' -DestinationPath 'dist\ArabicLens-Windows-x64.zip' -Force
Write-Host 'Portable app: dist\ArabicLens\ArabicLens.exe'
