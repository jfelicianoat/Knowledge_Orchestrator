"""Catálogo de modelos que el Broker dice tener disponibles."""
from __future__ import annotations

import json
from typing import Any

from knowledge_orchestrator.repositories.workflow_repository.estado import EstadoMixin


class ModelosMixin(EstadoMixin):
    """Persistencia del catálogo descubierto."""

    def upsert_models(self, models: list[dict[str, Any]], discovered_at: str) -> None:
        with self.database.transaction(immediate=True) as connection:
            for model in models:
                connection.execute(
                    "INSERT INTO model_catalog(name, provider, status, context_window, "
                    "capabilities_json, discovered_at) "
                    "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(name, provider) DO UPDATE SET status = excluded.status, "
                    "context_window = excluded.context_window, capabilities_json = excluded.capabilities_json, "
                    "discovered_at = excluded.discovered_at",
                    (
                        model["name"],
                        model.get("provider", "unknown"),
                        model["status"],
                        model.get("context_window"),
                        json.dumps(model, ensure_ascii=False),
                        discovered_at,
                    ),
                )
