@echo off
cd /d "%~dp0"
if exist "dist\ArabicLens\ArabicLens.exe" (
    start "" "dist\ArabicLens\ArabicLens.exe"
) else if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "main.py"
) else (
    echo Run Setup.ps1 first, or use the portable build.
    pause
)
