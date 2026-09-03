"""Persistencia de workflows y tareas Broker.

Esta capa no decide prompts ni chunks; su trabajo es dejar cada transicion
durable para que un reinicio no duplique envios ni pierda resultados.

El repositorio está partido por lo que hace, no por la tabla que toca:

- `filas`         — traducción de filas SQLite a registros del dominio.
- `base`          — estado y política de fallback del consenso.
- `planificacion` — alta de workflows y tareas, y recuperación de lo interrumpido.
- `consulta`      — lecturas sin efectos.
- `envio`         — tomar, aceptar, soltar o fallar un envío al Broker.
- `control`       — cancelar, reintentar e ignorar (lo que pide el operador).
- `estado`        — `apply_status` y el cierre del workflow.
- `modelos`       — catálogo de modelos descubiertos.

`WorkflowRepository` los recompone: quien lo usa importa esta clase y no
necesita saber en qué módulo vive cada método.
"""
from __future__ import annotations

from knowledge_orchestrator.repositories.workflow_repository.modelos import ModelosMixin

__all__ = ["WorkflowRepository"]


class WorkflowRepository(ModelosMixin):
    """Persistencia de workflows y tareas Broker."""
