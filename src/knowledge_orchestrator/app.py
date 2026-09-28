from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from knowledge_orchestrator.config import PipelinePaths
from knowledge_orchestrator.runtime import OrchestratorRuntime, build_runtime
from knowledge_orchestrator.services.operations import (
    RestoreError,
    backup_database,
    create_full_backup,
    export_diagnostics,
    restore_full_backup,
)
from knowledge_orchestrator.services.path_settings import load_pipeline_paths
from knowledge_orchestrator.ui.desktop_bootstrap import load_dashboard


def initialize_phase_one(paths: PipelinePaths | None = None) -> OrchestratorRuntime:
    return build_runtime(paths)


def startup_fallback(paths: PipelinePaths, error: Exception) -> PipelinePaths | None:
    """Pregunta si arrancar con las carpetas locales por defecto cuando las guardadas fallan."""

    import tkinter as tk
    from tkinter import messagebox

    local = PipelinePaths.defaults(home=Path.home())
    root = tk.Tk()
    root.withdraw()
    try:
        accepted = messagebox.askyesno(
            "No se pueden abrir las carpetas configuradas",
            f"No se pudo usar la carpeta de datos:\n{paths.state.parent}\n\n{type(error).__name__}: {error}\n\n"
            "¿Arrancar con carpetas locales de este equipo? Tus datos anteriores no se tocan; cuando la "
            "ubicación vuelva a estar disponible podrás elegirla de nuevo en Ajustes.",
            parent=root,
        )
    finally:
        root.destroy()
    return local if accepted else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Knowledge Orchestrator")
    parser.add_argument("--once", action="store_true", help="recupera e ingiere el inbox y termina")
    parser.add_argument("--ui", action="store_true", help="abre la interfaz visual Tk de cola y revisión")
    parser.add_argument('--api', action='store_true', help='inicia API local autenticada y workers')
    parser.add_argument('--api-port', type=int, default=8766, help='puerto local de Knowledge API')
    parser.add_argument("--backup", action="store_true", help="crea un backup consistente de SQLite y termina")
    parser.add_argument("--full-backup", action="store_true",
                        help="crea un ZIP restaurable (SQLite, fuentes y manifiesto) y termina")
    parser.add_argument("--restore", type=str, help="restaura un ZIP de --full-backup en la carpeta vacía --root")
    parser.add_argument("--diagnostics", type=str, help="exporta un ZIP diagnóstico sin secretos y termina")
    parser.add_argument("--root", type=str, help="raíz alternativa para pruebas locales")
    parser.add_argument("--scan-interval", type=float, default=5.0, help="rescan de seguridad en segundos")
    arguments = parser.parse_args()
    if arguments.restore:
        # Se restaura antes de construir el runtime: la raíz tiene que estar vacía.
        if not arguments.root:
            parser.error("--restore exige --root con una carpeta vacía")
        try:
            restored = restore_full_backup(Path(arguments.restore), Path(arguments.root))
        except RestoreError as error:
            parser.exit(2, f"No se restauró la copia: {error}\n")
        print(f"Copia restaurada en {restored.root}: {restored.files} archivos verificados. "
              "Vuelva a configurar el Broker y Obsidian en Ajustes.")
        return
    paths = PipelinePaths.under(Path(arguments.root)) if arguments.root else load_pipeline_paths()
    desktop = arguments.ui or bool(getattr(sys, "frozen", False))
    try:
        runtime = build_runtime(paths, scan_interval_seconds=arguments.scan_interval, enable_logging=True)
    except (OSError, sqlite3.Error) as error:
        if not desktop:
            raise
        # La ubicación guardada no está disponible (unidad desconectada, sin
        # permisos): se ofrece arrancar con carpetas locales en vez de cerrar
        # antes de que la persona pueda llegar a Ajustes (auditoría H09).
        fallback = startup_fallback(paths, error)
        if fallback is None:
            return
        runtime = build_runtime(fallback, scan_interval_seconds=arguments.scan_interval, enable_logging=True)
    if arguments.backup:
        result = backup_database(runtime.database, runtime.paths)
        print(f"Backup creado: {result.path} ({result.size_bytes} bytes)")
    elif arguments.full_backup:
        full = create_full_backup(runtime.database, runtime.paths)
        print(f"Copia integral creada: {full.path} ({full.files} archivos, {full.vault_notes} notas referenciadas)")
    elif arguments.diagnostics:
        diagnostics = export_diagnostics(
            runtime.database,
            runtime.paths,
            runtime.broker_worker.settings,
            output_path=Path(arguments.diagnostics),
        )
        print(f"Diagnóstico creado: {diagnostics.path}")
    elif arguments.api:
        from knowledge_orchestrator.api.server import serve

        serve(runtime, port=arguments.api_port)
    elif arguments.once:
        report = runtime.recover_once(ingest_inbox=True)
        print(f"Recuperación e ingesta completadas: {report}")
    elif arguments.ui or getattr(sys, "frozen", False):
        load_dashboard()(runtime)
    else:
        runtime.run_forever()


if __name__ == "__main__":
    main()
