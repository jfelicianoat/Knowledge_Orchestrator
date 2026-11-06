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

# El Python del proyecto y no el del PATH: el 3.11 del sistema trae SQLite 3.45.1,
# que falla con «NOT NULL constraint failed» en la migración 006 (ADD COLUMN NOT NULL
# DEFAULT … CHECK). El ejecutable 0.5.x compilado así no arrancaba en una carpeta nueva.
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

Invoke-Native { & $Python -m pip install --upgrade pip } "Actualizar pip"
Invoke-Native { & $Python -m pip install -e . } "Instalar el proyecto"
Invoke-Native { & $Python -m pip install pyinstaller } "Instalar PyInstaller"

# PyInstaller excluye Tkinter silenciosamente cuando Tcl/Tk está incompleto.
# Este preflight evita entregar un ejecutable que se cierra al arrancar.
& $Python -c "import tkinter as tk; root = tk.Tk(); root.withdraw(); root.update_idletasks(); root.destroy()"
if ($LASTEXITCODE -ne 0) {
    throw "La instalación de Python no tiene un Tcl/Tk funcional. Repara Python antes de generar la app Windows."
}

# Todas las migraciones sobre una base vacía con el SQLite que irá dentro del ejecutable.
Invoke-Native { & $Python -c "import sys, tempfile, pathlib; sys.path.insert(0, 'src'); from knowledge_orchestrator.repositories.database import Database; Database(pathlib.Path(tempfile.mkdtemp()) / 'preflight.db').initialize(); print('Migraciones aplicadas en una base nueva')" } "Comprobar migraciones en una base nueva"

# PyInstaller resuelve --add-data desde --specpath (build/pyinstaller), no desde
# el proyecto: con una ruta relativa no encuentra las migraciones y aborta.
$Migrations = Join-Path $ProjectRoot "src\knowledge_orchestrator\migrations"
Invoke-Native { & $Python -m PyInstaller `
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
        Invoke-Native { & $Compiler "scripts\knowledge_orchestrator.iss" } "Inno Setup"
        Write-Host "Instalador creado en $OutputDir\installer"
    } else {
        Write-Warning "Inno Setup 6 no está instalado; la aplicación portable sí se ha creado."
        Write-Warning "Instala Inno Setup y repite el script para generar el instalador de Windows."
    }
}
