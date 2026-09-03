"""Persistencia del ciclo semántico: afirmaciones, candidatos y trabajos.

El repositorio está partido por lo que persiste:

- `filas`         — normalización de texto y traducción de filas.
- `base`          — conexión y contexto de la nota.
- `afirmaciones`  — alta, consulta y búsqueda de relacionadas.
- `candidatos`    — propuesta, comparación y aplicación al vault.
- `trabajos`      — la cola durable contra el Broker.
- `embeddings`    — vectores y vecinos más cercanos.

`SemanticRepository` los recompone.
"""
from __future__ import annotations

from knowledge_orchestrator.repositories.semantic_repository.embeddings import EmbeddingsMixin
from knowledge_orchestrator.repositories.semantic_repository.filas import normalize_text

__all__ = ["SemanticRepository", "normalize_text"]


class SemanticRepository(EmbeddingsMixin):
    """Persistencia del ciclo semántico completo."""
