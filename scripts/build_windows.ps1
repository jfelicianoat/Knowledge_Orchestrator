param(
    [string]$OutputDir = "dist",
    [switch]$Clean,
    [switch]$SkipInstaller
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

# PyInstaller excluye Tkinter silenciosamente cuando Tcl/Tk está incompleto.
# Este preflight evita entregar un ejecutable que se cierra al arrancar.
python -c "import tkinter as tk; root = tk.Tk(); root.withdraw(); root.update_idletasks(); root.destroy()"
if ($LASTEXITCODE -ne 0) {
    throw "La instalación de Python no tiene un Tcl/Tk funcional. Repara Python antes de generar la app Windows."
}

python -m PyInstaller `
    --name Knowledge-Orchestrator `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --add-data "src/knowledge_orchestrator/migrations;knowledge_orchestrator/migrations" `
    --distpath $OutputDir `
    --workpath build/pyinstaller `
    --specpath build/pyinstaller `
    src/knowledge_orchestrator/app.py

Write-Host "Build creada en $OutputDir\Knowledge-Orchestrator"
Write-Host "Los datos de usuario permanecen fuera del ejecutable, en el perfil local de Windows."

if (-not $SkipInstaller) {
    $CompilerCandidates = @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )
    $Compiler = $CompilerCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if ($Compiler) {
        & $Compiler "scripts\knowledge_orchestrator.iss"
        Write-Host "Instalador creado en $OutputDir\installer"
    } else {
        Write-Warning "Inno Setup 6 no está instalado; la aplicación portable sí se ha creado."
        Write-Warning "Instala Inno Setup y repite el script para generar el instalador de Windows."
    }
}
