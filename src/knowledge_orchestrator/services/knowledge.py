"""Reconciliación de conocimiento: observa notas humanas sin sobrescribirlas."""
from __future__ import annotations

import hashlib
import json
from contextlib import closing
from pathlib import Path

from knowledge_orchestrator.repositories.knowledge_repository import KnowledgeRepository

#: Última observación de cada nota: (base, nota) -> (ruta, tamaño, mtime_ns, hash esperado, hash observado).
#: Con esto una lectura de la biblioteca no vuelve a leer y hashear todos los
#: ficheros de la bóveda cuando no ha cambiado nada (auditoría H18). Si cambian
#: el tamaño o la fecha, o el hash esperado, se vuelve a leer el fichero.
_OBSERVATIONS: dict[tuple[str, int], tuple[str, int, int, str, str | None]] = {}


def _observe(database_path: str, note_id: int, vault_path: str, expected: str) -> str | None:
    """Hash actual del fichero, reutilizando la observación anterior si no cambió."""

    path = Path(vault_path)
    stat = path.stat()
    key = (database_path, note_id)
    cached = _OBSERVATIONS.get(key)
    if cached and cached[:4] == (vault_path, stat.st_size, stat.st_mtime_ns, expected):
        return cached[4]
    observed = hashlib.sha256(path.read_bytes()).hexdigest()
    _OBSERVATIONS[key] = (vault_path, stat.st_size, stat.st_mtime_ns, expected, observed)
    return observed


class KnowledgeService:
    def __init__(self, repository: KnowledgeRepository) -> None:
        self.repository = repository

    def reconcile(self) -> dict[int, str]:
        database = self.repository.database
        with closing(database.connect(readonly=True)) as connection:
            notes = connection.execute(
                "SELECT note_id, vault_path, content_hash FROM notes WHERE status = 'PUBLISHED'"
            ).fetchall()
        with closing(database.connect(readonly=True)) as connection:
            known = {row['note_id']: (row['state'], row['observed_hash'], row['expected_hash'])
                     for row in connection.execute(
                         'SELECT note_id, state, observed_hash, expected_hash FROM knowledge_reconciliation')}
        result = {}
        for note in notes:
            try:
                observed = _observe(str(database.path), note['note_id'], note['vault_path'], note['content_hash'])
                state = 'IN_SYNC' if observed == note['content_hash'] else 'CONFLICT'
            except OSError:
                observed, state = None, 'MISSING'
            result[note['note_id']] = state
            if known.get(note['note_id']) == (state, observed, note['content_hash']):
                continue  # nada cambió: no se abre una transacción de escritura por nota
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
        self.repository.reconcile_derived_claims()
        return result
