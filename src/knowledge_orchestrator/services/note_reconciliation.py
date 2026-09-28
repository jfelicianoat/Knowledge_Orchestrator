"""Resolver desde la aplicación una nota que cambió o se movió en Obsidian (auditoría H14).

La reconciliación ya detectaba el cambio (CONFLICT) o la desaparición
(MISSING) y bloqueaba lo inseguro, pero no había forma de salir de ahí sin
tocar SQLite a mano. Tres salidas, todas sin sobrescribir el trabajo humano:

- Adoptar la versión de Obsidian: pasa a ser la versión oficial, se guarda
  como revisión, las afirmaciones de la versión anterior dejan de ser vigentes,
  las propuestas que dependían de ellas se bloquean y la nota se reanaliza.
- Localizar la nota movida: se acepta el nuevo sitio si el contenido es el
  mismo; si además cambió, queda como edición pendiente de adoptar.
- Retirar la nota del índice: deja de consultarse, sin borrar nada.
"""
from __future__ import annotations

import hashlib
import json
from contextlib import closing
from pathlib import Path
from typing import Any

from knowledge_orchestrator.domain.knowledge import KnowledgeConflict
from knowledge_orchestrator.repositories.database import Database
from knowledge_orchestrator.repositories.maintenance_states import note_in_reversion

EDIT_REASON = "Edición humana adoptada desde Obsidian"


class NoteReconciliationService:
    def __init__(self, database: Database, vault: Path, semantic: Any) -> None:
        self.database = database
        self.vault = vault
        self.semantic = semantic

    def issues(self) -> list[dict[str, Any]]:
        """Notas publicadas cuyo fichero ya no coincide con lo registrado."""

        with closing(self.database.connect(readonly=True)) as connection:
            return [dict(row) for row in connection.execute(
                "SELECT n.note_id, c.title, n.vault_path, r.state, r.expected_hash, r.observed_hash, r.checked_at, "
                "(SELECT COUNT(*) FROM knowledge_claims k WHERE k.note_id = n.note_id AND k.status = 'ACTIVE') "
                "AS claims FROM knowledge_reconciliation r JOIN notes n ON n.note_id = r.note_id "
                "JOIN captures c ON c.capture_id = n.capture_id "
                "WHERE n.status = 'PUBLISHED' AND r.state IN ('CONFLICT', 'MISSING') ORDER BY r.checked_at DESC"
            )]

    def current_text(self, note_id: int) -> tuple[str, str]:
        """Contenido actual del fichero y su hash, para enseñarlo antes de adoptar."""

        path = self._note_path(note_id)
        content = path.read_bytes()
        return content.decode("utf-8", errors="replace"), hashlib.sha256(content).hexdigest()

    def adopt_external_version(self, note_id: int, observed_hash: str, *, actor: str = "user:desktop") -> str:
        """Adopta exactamente la versión que la persona vio (por hash) y reanaliza."""

        path = self._note_path(note_id)
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if digest != observed_hash:
            raise KnowledgeConflict("La nota volvió a cambiar desde que la abriste; revísala otra vez")
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise KnowledgeConflict("La nota no está en UTF-8; guárdala así en Obsidian antes de adoptarla") from error
        with self.database.transaction(immediate=True) as connection:
            note = connection.execute(
                "SELECT n.capture_id, n.content_hash, r.state FROM notes n "
                "LEFT JOIN knowledge_reconciliation r ON r.note_id = n.note_id "
                "WHERE n.note_id = ? AND n.status = 'PUBLISHED'", (note_id,),
            ).fetchone()
            if note is None:
                raise LookupError("Nota publicada inexistente")
            if note["content_hash"] == digest:
                return ""
            if note_in_reversion(connection, note_id) or connection.execute(
                "SELECT 1 FROM update_candidates WHERE target_note_id = ? AND status = 'APPLYING'", (note_id,),
            ).fetchone():
                raise KnowledgeConflict("La nota tiene una aplicación en curso; espera a que termine")
            revision = connection.execute(
                "SELECT COALESCE(MAX(revision), 0) + 1 FROM note_revisions WHERE note_id = ?", (note_id,),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO note_revisions(note_id, revision, content_text, content_hash, reason) "
                "VALUES (?, ?, ?, ?, ?)", (note_id, revision, text, digest, EDIT_REASON),
            )
            connection.execute(
                "UPDATE notes SET content_hash = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE note_id = ?", (digest, note_id),
            )
            connection.execute(
                "INSERT INTO knowledge_reconciliation(note_id, state, expected_hash, observed_hash) "
                "VALUES (?, 'IN_SYNC', ?, ?) ON CONFLICT(note_id) DO UPDATE SET state = 'IN_SYNC', "
                "expected_hash = excluded.expected_hash, observed_hash = excluded.observed_hash, "
                "checked_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')", (note_id, digest, digest),
            )
            retired = self._retire_claims(connection, note_id, actor=actor,
                                          reason="La nota se editó en Obsidian; se reanaliza la versión nueva")
            connection.execute(
                "INSERT INTO events(capture_id, event_type, message, details_json) "
                "VALUES (?, 'NOTE_EDIT_ADOPTED', ?, ?)",
                (note["capture_id"], f"Edición de Obsidian adoptada; {retired} afirmación(es) pasan a histórico "
                                     "y la nota se vuelve a analizar.",
                 json.dumps({"note_id": note_id, "revision": revision, "actor": actor})),
            )
        return self._reanalyze(note_id)

    def relocate(self, note_id: int, new_path: Path, *, actor: str = "user:desktop") -> str:
        """Acepta el nuevo sitio de una nota movida. Devuelve el estado resultante."""

        resolved = Path(new_path).resolve()
        if not resolved.is_relative_to(self.vault.resolve()):
            raise KnowledgeConflict("El fichero elegido está fuera de la bóveda configurada")
        digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
        with self.database.transaction(immediate=True) as connection:
            note = connection.execute(
                "SELECT capture_id, content_hash FROM notes WHERE note_id = ? AND status = 'PUBLISHED'", (note_id,),
            ).fetchone()
            if note is None:
                raise LookupError("Nota publicada inexistente")
            taken = connection.execute(
                "SELECT 1 FROM notes WHERE vault_path = ? AND note_id <> ? AND status = 'PUBLISHED'",
                (str(resolved), note_id),
            ).fetchone()
            if taken:
                raise KnowledgeConflict("Ese fichero ya pertenece a otra nota publicada")
            state = "IN_SYNC" if digest == note["content_hash"] else "CONFLICT"
            connection.execute(
                "UPDATE notes SET vault_path = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE note_id = ?", (str(resolved), note_id),
            )
            connection.execute(
                "INSERT INTO knowledge_reconciliation(note_id, state, expected_hash, observed_hash) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(note_id) DO UPDATE SET state = excluded.state, "
                "expected_hash = excluded.expected_hash, observed_hash = excluded.observed_hash, "
                "checked_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')", (note_id, state, note["content_hash"], digest),
            )
            connection.execute(
                "INSERT INTO events(capture_id, event_type, message, details_json) VALUES (?, 'NOTE_RELOCATED', ?, ?)",
                (note["capture_id"], "Nota localizada en su nuevo sitio"
                 + ("" if state == "IN_SYNC" else "; además cambió y hay que revisar la edición"),
                 json.dumps({"note_id": note_id, "path": str(resolved), "actor": actor})),
            )
        return state

    def retire(self, note_id: int, *, actor: str = "user:desktop") -> None:
        """Retira la nota del conocimiento consultable. No borra el fichero ni la evidencia."""

        with self.database.transaction(immediate=True) as connection:
            note = connection.execute(
                "SELECT capture_id FROM notes WHERE note_id = ? AND status = 'PUBLISHED'", (note_id,),
            ).fetchone()
            if note is None:
                raise LookupError("Nota publicada inexistente")
            if note_in_reversion(connection, note_id) or connection.execute(
                "SELECT 1 FROM update_candidates WHERE target_note_id = ? AND status = 'APPLYING'", (note_id,),
            ).fetchone():
                raise KnowledgeConflict("La nota tiene una aplicación en curso; espera a que termine")
            self._retire_claims(connection, note_id, actor=actor, reason="Nota retirada del índice")
            connection.execute(
                "UPDATE notes SET status = 'RETIRED', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE note_id = ?", (note_id,),
            )
            connection.execute(
                "INSERT INTO events(capture_id, event_type, message, details_json) VALUES (?, 'NOTE_RETIRED', ?, ?)",
                (note["capture_id"], "Nota retirada del índice; el fichero y su historial se conservan",
                 json.dumps({"note_id": note_id, "actor": actor})),
            )

    def _note_path(self, note_id: int) -> Path:
        with closing(self.database.connect(readonly=True)) as connection:
            row = connection.execute(
                "SELECT vault_path FROM notes WHERE note_id = ? AND status = 'PUBLISHED'", (note_id,),
            ).fetchone()
        if row is None:
            raise LookupError("Nota publicada inexistente")
        path = Path(row["vault_path"]).resolve()
        if not path.is_relative_to(self.vault.resolve()):
            raise KnowledgeConflict("La nota queda fuera de la bóveda configurada")
        return path

    @staticmethod
    def _retire_claims(connection: Any, note_id: int, *, actor: str, reason: str) -> int:
        """Las afirmaciones de la versión anterior pasan a histórico y sus propuestas se bloquean."""

        claims = [row["claim_id"] for row in connection.execute(
            "SELECT claim_id FROM knowledge_claims WHERE note_id = ? AND status = 'ACTIVE'", (note_id,),
        )]
        for claim_id in claims:
            row = connection.execute("SELECT * FROM knowledge_claims WHERE claim_id = ?", (claim_id,)).fetchone()
            connection.execute(
                "UPDATE knowledge_claims SET status = 'RETRACTED', knowledge_state = 'HISTORICAL', "
                "valid_until = COALESCE(valid_until, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')), revision = revision + 1, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE claim_id = ?", (claim_id,),
            )
            connection.execute(
                "INSERT INTO claim_state_history(claim_id, revision, from_state, to_state, valid_from, actor, reason, "
                "candidate_id) VALUES (?, ?, ?, 'HISTORICAL', ?, ?, ?, NULL)",
                (claim_id, row["revision"] + 1, row["knowledge_state"], row["valid_from"], actor, reason),
            )
        if claims:
            marks = ",".join("?" for _ in claims)
            connection.execute(
                "UPDATE update_candidates SET status = 'CONFLICT', blocked_reason = ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE status IN ('PENDING_COMPARISON', 'PENDING_REVIEW') "
                f"AND (target_claim_id IN ({marks}) OR new_claim_id IN ({marks}))",
                (reason, *claims, *claims),
            )
        return len(claims)

    def _reanalyze(self, note_id: int) -> str:
        repository = self.semantic.repository
        for job in repository.extraction_jobs(note_id):
            if job.status in {"READY", "SUBMITTING", "QUEUED", "PROCESSING"}:
                # Analizaba la versión anterior: su resultado ya no encajaría.
                repository.fail_job(job.job_id, "SUPERSEDED_BY_EDIT", "La nota se editó en Obsidian")
        attempts = len(repository.extraction_jobs(note_id))
        return str(self.semantic._create_extraction_job(note_id, attempt=attempts + 1))
