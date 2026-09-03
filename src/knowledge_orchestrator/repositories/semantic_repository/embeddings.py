"""Vectores de las afirmaciones y búsqueda de las más cercanas.

El coseno se calcula aquí, sobre lo que hay guardado: sin dependencias
numéricas nuevas para una operación que son tres líneas.
"""
from __future__ import annotations

import json
import math
from collections.abc import Iterable
from contextlib import closing

from knowledge_orchestrator.repositories.semantic_repository.trabajos import TrabajosMixin


class EmbeddingsMixin(TrabajosMixin):
    """Persistencia y consulta de embeddings de afirmaciones."""

    def record_embedding(self, claim_id: int, model: str, vector: Iterable[float]) -> None:
        values = [float(value) for value in vector]
        if not values or any(not math.isfinite(value) for value in values):
            raise ValueError("Embedding inválido")
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT INTO claim_embeddings(claim_id, model, dimensions, vector_json) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(claim_id) DO UPDATE SET model = excluded.model, dimensions = excluded.dimensions, "
                "vector_json = excluded.vector_json, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
                (claim_id, model, len(values), json.dumps(values)),
            )

    def nearest_embeddings(self, claim_id: int, *, limit: int = 10, minimum_similarity: float = 0.75) -> list[int]:
        with closing(self.database.connect()) as connection:
            source = connection.execute(
                "SELECT model, dimensions, vector_json FROM claim_embeddings WHERE claim_id = ?", (claim_id,)
            ).fetchone()
            if source is None:
                return []
            rows = connection.execute(
                "SELECT e.claim_id, e.vector_json FROM claim_embeddings e "
                "JOIN knowledge_claims k ON k.claim_id = e.claim_id "
                "JOIN notes n ON n.note_id = k.note_id "
                "WHERE e.claim_id <> ? AND e.model = ? AND e.dimensions = ? AND k.status = 'ACTIVE' "
                "AND n.status = 'PUBLISHED'",
                (claim_id, source["model"], source["dimensions"]),
            ).fetchall()
        origin = json.loads(source["vector_json"])
        norm_origin = math.sqrt(sum(value * value for value in origin))
        scored: list[tuple[float, int]] = []
        for row in rows:
            vector = json.loads(row["vector_json"])
            norm = math.sqrt(sum(value * value for value in vector))
            # strict=False conserva la semántica previa: un vector de otra
            # dimensión trunca el producto en vez de romper el mantenimiento.
            dot = sum(a * b for a, b in zip(origin, vector, strict=False))
            similarity = dot / (norm_origin * norm) if norm_origin and norm else 0.0
            if similarity >= minimum_similarity:
                scored.append((similarity, int(row["claim_id"])))
        return [claim for _, claim in sorted(scored, reverse=True)[:limit]]
