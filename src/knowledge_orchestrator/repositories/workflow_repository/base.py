"""Estado del repositorio, política de fallback y fallo del workflow.

`_fail_workflow` está aquí y no en `estado` porque lo usan también la
planificación y el envío: un fallo en cualquiera de los tres sitios tiene
que dejar el workflow y la captura en el mismo estado.
"""
from __future__ import annotations

import sqlite3

from knowledge_orchestrator.repositories.database import Database


class RepositorioBase:
    """Estado compartido por todas las partes del repositorio.

    Esta capa no decide prompts ni chunks; su trabajo es dejar cada transicion
    durable para que un reinicio no duplique envios ni pierda resultados.
    """

    # El fallback a single solo vale para fallos de capacidad/quorum del consenso.
    # Otros errores siguen siendo terminales, porque repetir en single podria ocultar problemas reales.
    CONSENSUS_FALLBACK_CODES = {
        "CONSENSUS_QUORUM_NOT_REACHED",
        "CONSENSUS_PRESET_NOT_IMPLEMENTED",
        "VRAM_INSUFFICIENT",
        "MODEL_UNAVAILABLE",
        "PROVIDER_UNAVAILABLE",
    }
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _fail_workflow(
        connection: sqlite3.Connection,
        workflow_id: str,
        capture_id: str,
        code: str,
        message: str,
    ) -> None:
        connection.execute(
            "UPDATE workflows SET status = 'ERROR', error_code = ?, error_message = ?, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE workflow_id = ?",
            (code, message, workflow_id),
        )
        connection.execute(
            "UPDATE captures SET status = 'FAILED', last_error_code = ?, last_error_message = ?, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE capture_id = ?",
            (code, message, capture_id),
        )
