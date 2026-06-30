# Fase 8 — Empaquetado y operación

## Estado

Primera entrega implementada y verificada. El Orchestrator dispone de logging estructurado rotativo, backup consistente de SQLite, export diagnóstico sin secretos y script de build Windows.

## Alcance implementado

- Logging JSON en `logs/orchestrator.log` con rotación por tamaño.
- Backup SQLite consistente mediante la API `sqlite3.Connection.backup`, guardado en `backups/`.
- Export diagnóstico ZIP con:
  - `diagnostics.json` con versión de Python, plataforma, rutas, settings redacted, contadores de DB y resumen de directorios;
  - cola de log saneada;
  - README del paquete.
- Redacción de claves y patrones sensibles: `token`, `secret`, `password`, `api_key`, `authorization`, `cookie` y credenciales embebidas en URL.
- CLI:
  - `--backup`
  - `--diagnostics <ruta.zip>`
- Script `scripts/build_windows.ps1` para generar una build `onedir` con PyInstaller.

## Restricciones operativas

- El ZIP diagnóstico no incluye la base SQLite ni contenido de notas.
- Los datos de usuario permanecen fuera del ejecutable: `C:/YT-Pipeline` y el vault configurado.
- El backup copia una vista consistente de SQLite; no mueve ni bloquea el pipeline de trabajo.
- El script de build no empaqueta datos del usuario.

## Comandos

```powershell
$env:PYTHONPATH='src'
python -m knowledge_orchestrator.app --backup
python -m knowledge_orchestrator.app --diagnostics C:\tmp\ko-diagnostics.zip
```

Build Windows:

```powershell
.\scripts\build_windows.ps1 -Clean
```

## Verificación

- `tests/test_phase_eight_operations.py` cubre logging, backup, diagnóstico y redacción.
- `python -m knowledge_orchestrator.app --help` muestra las nuevas opciones.
- La suite completa debe ejecutarse con:

```powershell
$env:PYTHONPATH='src'
python -m unittest discover -s tests -v
```

## Pendiente para cierre operativo final

- Ejecutar la build en un entorno Windows limpio.
- Prueba end-to-end real Plugin → Orchestrator → Broker → Obsidian con datos de prueba.
- Decidir si se quiere instalador `.msi`/`Inno Setup` o distribución `onedir` es suficiente para el TFM.
