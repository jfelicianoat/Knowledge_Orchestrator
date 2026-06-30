param(
    [string]$OutputDir = "dist",
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

if ($Clean) {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue build, $OutputDir
}

python -m pip install --upgrade pip
python -m pip install -e .
python -m pip install pyinstaller

python -m PyInstaller `
    --name Knowledge-Orchestrator `
    --noconfirm `
    --clean `
    --onedir `
    --add-data "src/knowledge_orchestrator/migrations;knowledge_orchestrator/migrations" `
    --distpath $OutputDir `
    --workpath build/pyinstaller `
    --specpath build/pyinstaller `
    src/knowledge_orchestrator/app.py

Write-Host "Build creada en $OutputDir\Knowledge-Orchestrator"
Write-Host "Los datos de usuario permanecen fuera del ejecutable: C:\YT-Pipeline y el vault configurado."
