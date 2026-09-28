"""Estado del repositorio, política de fallback y fallo del workflow.

`_fail_workflow` está aquí y no en `estado` porque lo usan también la
planificación y el envío: un fallo en cualquiera de los tres sitios tiene
que dejar el workflow y la captura en el mismo estado.
"""
from __future__ import annotations

import sqlite3

from knowledge_orchestrator.repositories.database import Database

#: Estrategias que pueden caer a `single` y los fallos que lo permiten. Viven
#: aquí, en un solo sitio, porque la transición que decide no cerrar el workflow
#: y el planificador que crea la alternativa tienen que coincidir: con `auto`
#: fuera de la primera lista, el planificador encontraba el workflow ya cerrado
#: y el fallback era inalcanzable (auditoría H11). Presupuesto, privacidad y
#: contrato no están: repetir en single ocultaría el problema real.
FALLBACK_STRATEGIES = frozenset({"mixture_of_agents", "auto"})
CONSENSUS_FALLBACK_CODES = frozenset({
    "CONSENSUS_QUORUM_NOT_REACHED",
    "CONSENSUS_PRESET_NOT_IMPLEMENTED",
    "VRAM_INSUFFICIENT",
    "MODEL_UNAVAILABLE",
    "PROVIDER_UNAVAILABLE",
})


def fallback_eligible(strategy: str | None, allowed: bool, code: str | None) -> bool:
    return bool(allowed) and strategy in FALLBACK_STRATEGIES and code in CONSENSUS_FALLBACK_CODES


class RepositorioBase:
    """Estado compartido por todas las partes del repositorio.

    Esta capa no decide prompts ni chunks; su trabajo es dejar cada transicion
    durable para que un reinicio no duplique envios ni pierda resultados.
    """

    # El fallback a single solo vale para fallos de capacidad/quorum del consenso.
    # Otros errores siguen siendo terminales, porque repetir en single podria ocultar problemas reales.
    CONSENSUS_FALLBACK_CODES = CONSENSUS_FALLBACK_CODES
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
        # Un documento cancelado por su dueño sigue cancelado: los avisos que
        # lleguen después (la tarea cancelada en el Broker, un envío que falló)
        # no lo convierten en un error que pida atención.
        changed = connection.execute(
            "UPDATE workflows SET status = 'ERROR', error_code = ?, error_message = ?, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE workflow_id = ? AND status <> 'CANCELLED'",
            (code, message, workflow_id),
        )
        if not changed.rowcount:
            return
        connection.execute(
            "UPDATE captures SET status = 'FAILED', last_error_code = ?, last_error_message = ?, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE capture_id = ? AND status <> 'CANCELLED'",
            (code, message, capture_id),
        )
