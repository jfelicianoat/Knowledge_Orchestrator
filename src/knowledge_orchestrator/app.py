from __future__ import annotations

import argparse
from pathlib import Path

from knowledge_orchestrator.config import PipelinePaths
from knowledge_orchestrator.runtime import OrchestratorRuntime, build_runtime
from knowledge_orchestrator.ui.dashboard import run_dashboard


def initialize_phase_one(paths: PipelinePaths | None = None) -> OrchestratorRuntime:
    return build_runtime(paths)


def main() -> None:
    parser = argparse.ArgumentParser(description="Knowledge Orchestrator")
    parser.add_argument("--once", action="store_true", help="recupera e ingiere el inbox y termina")
    parser.add_argument("--ui", action="store_true", help="abre la interfaz visual Tk de cola y revisión")
    parser.add_argument("--root", type=str, help="raíz alternativa para pruebas locales")
    parser.add_argument("--scan-interval", type=float, default=5.0, help="rescan de seguridad en segundos")
    arguments = parser.parse_args()
    paths = PipelinePaths.under(Path(arguments.root)) if arguments.root else None
    runtime = build_runtime(paths, scan_interval_seconds=arguments.scan_interval)
    if arguments.once:
        report = runtime.recover_once(ingest_inbox=True)
        print(f"Recuperación e ingesta completadas: {report}")
    elif arguments.ui:
        run_dashboard(runtime)
    else:
        runtime.run_forever()


if __name__ == "__main__":
    main()
