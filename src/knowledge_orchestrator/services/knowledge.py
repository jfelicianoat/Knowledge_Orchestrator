"""Reconciliación de conocimiento: observa notas humanas sin sobrescribirlas."""
from __future__ import annotations

import hashlib
import json
from contextlib import closing
from pathlib import Path

from knowledge_orchestrator.repositories.knowledge_repository import KnowledgeRepository


class KnowledgeService:
    def __init__(self, repository: KnowledgeRepository) -> None:
        self.repository = repository

    def reconcile(self) -> dict[int, str]:
        database = self.repository.database
        with closing(database.connect(readonly=True)) as connection:
            notes = connection.execute(
                "SELECT note_id, vault_path, content_hash FROM notes WHERE status = 'PUBLISHED'"
            ).fetchall()
        result = {}
        for note in notes:
            try:
                observed = hashlib.sha256(Path(note['vault_path']).read_bytes()).hexdigest()
                state = 'IN_SYNC' if observed == note['content_hash'] else 'CONFLICT'
            except OSError:
                observed, state = None, 'MISSING'
            with database.transaction(immediate=True) as connection:
                # Una publicación concurrente invalida la observación; el próximo ciclo reintentará.
                current = connection.execute(
                    'SELECT content_hash FROM notes WHERE note_id = ?', (note['note_id'],),
                ).fetchone()
                if current is None or current[0] != note['content_hash']:
                    continue
                previous = connection.execute(
                    'SELECT state, observed_hash FROM knowledge_reconciliation WHERE note_id = ?', (note['note_id'],),
                ).fetchone()
                connection.execute(
                    'INSERT INTO knowledge_reconciliation(note_id, state, expected_hash, observed_hash) '
                    'VALUES (?, ?, ?, ?) ON CONFLICT(note_id) DO UPDATE SET state = excluded.state, '
                    'expected_hash = excluded.expected_hash, observed_hash = excluded.observed_hash, '
                    "checked_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
                    (note['note_id'], state, note['content_hash'], observed),
                )
                if previous is None or (previous['state'], previous['observed_hash']) != (state, observed):
                    connection.execute(
                        "INSERT INTO events(event_type, message, details_json) VALUES "
                        "('KNOWLEDGE_RECONCILED', 'Comprobación de coherencia documental', ?)",
                        (json.dumps({'note_id': note['note_id'], 'state': state}),),
                    )
            result[note['note_id']] = state
        self.repository.reconcile_derived_claims()
        return result
