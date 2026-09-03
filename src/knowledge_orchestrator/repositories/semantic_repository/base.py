"""Estado del repositorio semántico."""
from __future__ import annotations

import sqlite3
from contextlib import closing

from knowledge_orchestrator.repositories.database import Database


class RepositorioBase:
    """Conexión y contexto de la nota sobre la que se trabaja."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def note_context(self, note_id: int) -> sqlite3.Row:
        with closing(self.database.connect()) as connection:
            row = connection.execute(
                "SELECT n.note_id, n.capture_id, n.topic_id, n.vault_path, n.status, c.metadata_json "
                "FROM notes n JOIN captures c ON c.capture_id = n.capture_id WHERE n.note_id = ?",
                (note_id,),
            ).fetchone()
            if row is None:
                raise ValueError("Nota inexistente")
            return row
