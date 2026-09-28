param(
    [string]$OutputDir = "dist",
    [switch]$Clean,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

# En Windows PowerShell 5.1, con "Stop", cualquier línea que un programa
# escribe en stderr (PyInstaller registra ahí sus INFO) aborta el script. Los
# comandos nativos se juzgan por su código de salida, no por stderr.
function Invoke-Native {
    param([scriptblock]$Command, [string]$What)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $Command 2>&1 | ForEach-Object { "$_" } } finally { $ErrorActionPreference = $previous }
    if ($LASTEXITCODE -ne 0) { throw "$What falló (código $LASTEXITCODE)" }
}

if ($Clean) {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue build, $OutputDir
}

Invoke-Native { python -m pip install --upgrade pip } "Actualizar pip"
Invoke-Native { python -m pip install -e . } "Instalar el proyecto"
Invoke-Native { python -m pip install pyinstaller } "Instalar PyInstaller"

# PyInstaller excluye Tkinter silenciosamente cuando Tcl/Tk está incompleto.
# Este preflight evita entregar un ejecutable que se cierra al arrancar.
python -c "import tkinter as tk; root = tk.Tk(); root.withdraw(); root.update_idletasks(); root.destroy()"
if ($LASTEXITCODE -ne 0) {
    throw "La instalación de Python no tiene un Tcl/Tk funcional. Repara Python antes de generar la app Windows."
}

# PyInstaller resuelve --add-data desde --specpath (build/pyinstaller), no desde
# el proyecto: con una ruta relativa no encuentra las migraciones y aborta.
$Migrations = Join-Path $ProjectRoot "src\knowledge_orchestrator\migrations"
Invoke-Native { python -m PyInstaller `
    --name Knowledge-Orchestrator `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --paths (Join-Path $ProjectRoot "src") `
    --add-data "$Migrations;knowledge_orchestrator/migrations" `
    --distpath $OutputDir `
    --workpath build/pyinstaller `
    --specpath build/pyinstaller `
    src/knowledge_orchestrator/app.py } "PyInstaller"

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
