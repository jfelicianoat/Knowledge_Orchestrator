$ErrorActionPreference = "Stop"

$vault = [System.IO.Path]::GetFullPath("Y:\Mi unidad\Vaults\Conocimiento_Youtube")
$internal = Join-Path $vault ".knowledge-orchestrator"
$legacyTargets = @(
    [System.IO.Path]::GetFullPath("C:\ObsidianVault\Knowledge"),
    [System.IO.Path]::GetFullPath("C:\YT-Pipeline"),
    [System.IO.Path]::GetFullPath("C:\Users\jfeli\Downloads\YT-Knowledge-Inbox")
)

if (-not (Get-PSDrive -Name "Y" -ErrorAction SilentlyContinue)) {
    throw "La unidad Y: no está disponible. Conecta Google Drive antes de continuar."
}

# Preflight: no se borra nada hasta confirmar que el destino exacto es accesible.
New-Item -ItemType Directory -Path $vault -Force | Out-Null
$probe = Join-Path $vault ".knowledge-orchestrator-write-test.tmp"
[System.IO.File]::WriteAllText($probe, "ok")
Remove-Item -LiteralPath $probe -Force

$deleteTargets = @($vault) + $legacyTargets
foreach ($target in $deleteTargets) {
    $absolute = [System.IO.Path]::GetFullPath($target)
    if ($absolute -notin $deleteTargets) {
        throw "Destino de limpieza inesperado: $absolute"
    }
    if (Test-Path -LiteralPath $absolute) {
        Remove-Item -LiteralPath $absolute -Recurse -Force
    }
}

$managedFolders = @(
    "inbox", "staging", "processing", "completed", "failed",
    "failed\contracts", "failed\duplicates", "failed\transcriptions",
    "rejected", "state", "logs", "backups", "diagnostics"
)
New-Item -ItemType Directory -Path $vault -Force | Out-Null
foreach ($folder in $managedFolders) {
    New-Item -ItemType Directory -Path (Join-Path $internal $folder) -Force | Out-Null
}

$settingsPath = Join-Path $env:LOCALAPPDATA "Knowledge Orchestrator\config\paths.json"
$settingsDirectory = Split-Path -Parent $settingsPath
New-Item -ItemType Directory -Path $settingsDirectory -Force | Out-Null
$settings = @{
    data_root = $internal
    inbox = Join-Path $internal "inbox"
    obsidian_vault = $vault
} | ConvertTo-Json
$temporarySettings = "$settingsPath.tmp"
[System.IO.File]::WriteAllText($temporarySettings, $settings, [System.Text.UTF8Encoding]::new($false))
Move-Item -LiteralPath $temporarySettings -Destination $settingsPath -Force

Write-Host "Knowledge Orchestrator está vacío y preparado en:"
Write-Host "  Vault:   $vault"
Write-Host "  Entrada: $(Join-Path $internal 'inbox')"
Write-Host "  Estado:  $(Join-Path $internal 'state')"
