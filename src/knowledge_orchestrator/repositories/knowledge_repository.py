"""Entidades, consultas temporales y transiciones dentro de la transacción de publicación."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing

from knowledge_orchestrator.domain.knowledge import Entity, KnowledgeConflict, KnowledgeState
from knowledge_orchestrator.domain.semantic_models import KnowledgeClaim
from knowledge_orchestrator.repositories.database import Database
from knowledge_orchestrator.repositories.maintenance_states import claim_in_application, record_review_state


def register_claim(connection: sqlite3.Connection, claim_id: int, *, actor: str = 'extraction',
                   reason: str = 'Extracción con evidencia local') -> None:
    """Completa el alta en la misma transacción que el claim y su evidencia."""
    connection.execute(
        "UPDATE knowledge_claims SET valid_from = created_at WHERE claim_id = ? AND valid_from IS NULL",
        (claim_id,),
    )
    connection.execute(
        "INSERT INTO knowledge_entities(name, entity_key) "
        "SELECT trim(j.value), lower(trim(j.value)) FROM knowledge_claims k, json_each(k.entities_json) j "
        "WHERE k.claim_id = ? AND j.type = 'text' AND length(trim(j.value)) > 0 "
        "ON CONFLICT(entity_key) DO NOTHING", (claim_id,),
    )
    connection.execute(
        "INSERT OR IGNORE INTO claim_entities(claim_id, entity_id) "
        "SELECT k.claim_id, e.entity_id FROM knowledge_claims k, json_each(k.entities_json) j "
        "JOIN knowledge_entities e ON e.entity_key = lower(trim(j.value)) WHERE k.claim_id = ?",
        (claim_id,),
    )
    connection.execute(
        "INSERT INTO claim_state_history(claim_id, revision, to_state, valid_from, actor, reason) "
        'SELECT claim_id, revision, knowledge_state, valid_from, ?, ? '
        'FROM knowledge_claims WHERE claim_id = ? ON CONFLICT(claim_id, revision) DO NOTHING',
        (actor, reason, claim_id),
    )


def record_supersession(connection: sqlite3.Connection, candidate_id: int, *, successor_id: int | None = None) -> None:
    """No aplica propuestas: registra una aplicación ya materializada, de forma recuperable."""
    candidate = connection.execute(
        "SELECT * FROM update_candidates WHERE candidate_id = ? AND status = 'APPLYING'", (candidate_id,),
    ).fetchone()
    if candidate is None:
        raise KnowledgeConflict('No existe una intención de aplicación')
    target = connection.execute(
        "SELECT * FROM knowledge_claims WHERE claim_id = ?", (candidate['target_claim_id'],),
    ).fetchone()
    successor = connection.execute(
        "SELECT * FROM knowledge_claims WHERE claim_id = ?", (successor_id or candidate['new_claim_id'],),
    ).fetchone()
    if target is None or successor is None or target['claim_id'] == successor['claim_id']:
        raise KnowledgeConflict('La sucesión requiere dos claims distintos')
    if target['manual_lock'] or successor['manual_lock']:
        raise KnowledgeConflict('MANUAL_LOCK')
    if target['status'] != 'ACTIVE' or successor['knowledge_state'] != 'CURRENT':
        raise KnowledgeConflict('El estado de los claims cambió durante la revisión')
    if not candidate['rationale'] or not candidate['patch_json']:
        raise KnowledgeConflict('La actualización requiere propuesta explicada')
    for claim in (target, successor):
        if connection.execute(
            'SELECT 1 FROM evidence_links WHERE claim_id = ?', (claim['claim_id'],),
        ).fetchone() is None:
            raise KnowledgeConflict('La actualización requiere evidencia de ambos claims')
    now = connection.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ', 'now')").fetchone()[0]
    # EXTENDS/CONTRADICTS reemplazan una formulación; no afirman sucesión factual.
    state = 'SUPERSEDED' if candidate['relation'] == 'SUPERSEDES' else 'HISTORICAL'
    connection.execute(
        "UPDATE knowledge_claims SET status = 'SUPERSEDED', knowledge_state = ?, valid_until = ?, "
        "superseded_by = ?, revision = revision + 1, updated_at = ? WHERE claim_id = ?",
        (state, now, successor['claim_id'], now, target['claim_id']),
    )
    connection.execute(
        'INSERT INTO claim_state_history(claim_id, revision, from_state, to_state, valid_from, valid_until, '
        'superseded_by, actor, reason, candidate_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (target['claim_id'], target['revision'] + 1, target['knowledge_state'], state,
         target['valid_from'], now, successor['claim_id'], candidate['reviewed_by'] or 'human:review',
         candidate['rationale'], candidate_id),
    )
    connection.execute(
        "INSERT INTO events(event_type, message, details_json) VALUES "
        "('CLAIM_STATE_CHANGED', 'Transición de vigencia tras aprobación', ?)",
        (json.dumps({'claim_id': target['claim_id'], 'successor_id': successor['claim_id'],
                     'candidate_id': candidate_id, 'to_state': state}),),
    )


class KnowledgeRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def entities(self, *, limit: int = 100, offset: int = 0) -> list[Entity]:
        self._pagination(limit, offset)
        with closing(self.database.connect(readonly=True)) as connection:
            return [Entity(**dict(row)) for row in connection.execute(
                'SELECT entity_id, name, entity_key FROM knowledge_entities ORDER BY entity_id LIMIT ? OFFSET ?',
                (limit, offset),
            )]

    def entity(self, entity_id: int) -> Entity | None:
        with closing(self.database.connect(readonly=True)) as connection:
            row = connection.execute(
                'SELECT entity_id, name, entity_key FROM knowledge_entities WHERE entity_id = ?', (entity_id,),
            ).fetchone()
            return Entity(**dict(row)) if row else None

    def claims(
        self, *, state: str = 'current', entity_id: int | None = None, note_id: int | None = None,
        limit: int = 100, offset: int = 0,
    ) -> list[KnowledgeClaim]:
        from knowledge_orchestrator.repositories.semantic_repository.filas import _claim

        self._pagination(limit, offset)
        clauses, parameters = self.state_filter(state)
        if entity_id is not None:
            clauses.append(
                'EXISTS (SELECT 1 FROM claim_entities ce WHERE ce.claim_id = k.claim_id AND ce.entity_id = ?)'
            )
            parameters.append(entity_id)
        if note_id is not None:
            clauses.append('k.note_id = ?')
            parameters.append(note_id)
        with closing(self.database.connect(readonly=True)) as connection:
            rows = connection.execute(
                'SELECT k.* FROM knowledge_claims k WHERE ' + ' AND '.join(clauses or ['1=1']) +
                ' ORDER BY k.claim_id LIMIT ? OFFSET ?', [*parameters, limit, offset],
            )
            return [_claim(row) for row in rows]

    @staticmethod
    def provenance_filter() -> str:
        return (
            'NOT EXISTS (WITH RECURSIVE origins(claim_id,parent_id,note_id,status,knowledge_state,depth) AS ('
            'SELECT p.claim_id,p.derived_from_claim_id,p.note_id,p.status,p.knowledge_state,1 '
            'FROM knowledge_claims p WHERE p.claim_id=k.derived_from_claim_id UNION ALL '
            'SELECT p.claim_id,p.derived_from_claim_id,p.note_id,p.status,p.knowledge_state,o.depth+1 '
            'FROM origins o JOIN knowledge_claims p ON p.claim_id=o.parent_id WHERE o.depth<100) '
            "SELECT 1 FROM origins o WHERE o.status<>'ACTIVE' OR o.knowledge_state<>'CURRENT' OR o.depth=100 "
            "OR NOT EXISTS (SELECT 1 FROM notes n WHERE n.note_id=o.note_id AND n.status='PUBLISHED') "
            "OR EXISTS (SELECT 1 FROM knowledge_reconciliation r WHERE r.note_id=o.note_id AND r.state<>'IN_SYNC') "
            "OR EXISTS (SELECT 1 FROM update_candidates c WHERE c.target_note_id=o.note_id AND c.status='APPLYING') "
            "OR EXISTS (SELECT 1 FROM update_candidates c WHERE c.relation='CONTRADICTS' "
            "AND c.status IN ('PENDING_REVIEW','CONFLICT','APPLYING') "
            'AND (c.target_claim_id=o.claim_id OR c.new_claim_id=o.claim_id)))'
        )

    def reconcile_derived_claims(self) -> None:
        with self.database.transaction(immediate=True) as connection:
            rows = connection.execute(
                "SELECT k.claim_id FROM knowledge_claims k WHERE k.status='ACTIVE' AND k.knowledge_state='CURRENT' "
                'AND k.manual_lock=0 AND k.derived_from_claim_id IS NOT NULL AND NOT ('
                + self.provenance_filter() + ') '
                "AND NOT EXISTS (SELECT 1 FROM update_candidates c WHERE c.status='APPLYING' "
                'AND (c.target_note_id=k.note_id OR c.new_claim_id=k.claim_id))').fetchall()
            for row in rows:
                if claim_in_application(connection, row['claim_id']):
                    continue
                record_review_state(connection, row['claim_id'], 'REVIEW_REQUIRED', actor='system:reconciliation',
                                    reason='La evidencia de origen de la proyección dejó de estar vigente o coherente',
                                    candidate_id=None)

    @staticmethod
    def state_filter(state: str) -> tuple[list[str], list[object]]:
        value = state.upper()
        if value == 'ALL':
            return [], []
        if value == 'HISTORICAL':
            return ["k.knowledge_state IN ('HISTORICAL', 'SUPERSEDED')"], []
        if value not in {item.value for item in KnowledgeState}:
            raise ValueError('Estado de conocimiento inválido')
        clauses = ['k.knowledge_state = ?']
        if value == 'CURRENT':
            clauses.extend([
                KnowledgeRepository.provenance_filter(),
                "k.status = 'ACTIVE' AND k.valid_until IS NULL",
                "EXISTS (SELECT 1 FROM notes n WHERE n.note_id = k.note_id AND n.status = 'PUBLISHED')",
                "NOT EXISTS (SELECT 1 FROM knowledge_reconciliation r "
                "WHERE r.note_id = k.note_id AND r.state <> 'IN_SYNC')",
                "NOT EXISTS (SELECT 1 FROM update_candidates c "
                "WHERE c.target_note_id = k.note_id AND c.status = 'APPLYING')",
                "NOT EXISTS (SELECT 1 FROM update_candidates c WHERE c.relation='CONTRADICTS' "
                "AND c.status IN ('PENDING_REVIEW','CONFLICT','APPLYING') "
                'AND (c.target_claim_id=k.claim_id OR c.new_claim_id=k.claim_id))',
            ])
        return clauses, [value]

    def history(self, claim_id: int) -> list[dict[str, object]]:
        with closing(self.database.connect(readonly=True)) as connection:
            return [dict(row) for row in connection.execute(
                'SELECT * FROM claim_state_history WHERE claim_id = ? ORDER BY revision', (claim_id,),
            )]

    def review_state(
        self, claim_id: int, state: KnowledgeState, *, expected_revision: int, actor: str, reason: str,
    ) -> None:
        """Decisión humana sobre vigencia, sin publicar ni convertir antigüedad en falsedad."""
        state = KnowledgeState(state)
        if not actor.strip() or not reason.strip():
            raise ValueError('La revisión requiere actor y justificación')
        if state in {KnowledgeState.HISTORICAL, KnowledgeState.SUPERSEDED}:
            raise KnowledgeConflict('El paso a histórico requiere una propuesta de publicación')
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute('SELECT * FROM knowledge_claims WHERE claim_id = ?', (claim_id,)).fetchone()
            if row is None or row['revision'] != expected_revision:
                raise KnowledgeConflict('La revisión del claim cambió')
            if row['manual_lock']:
                raise KnowledgeConflict('MANUAL_LOCK')
            if row['status'] != 'ACTIVE':
                raise KnowledgeConflict('Un claim histórico no se puede reactivar')
            if claim_in_application(connection, claim_id):
                raise KnowledgeConflict('Hay una publicación pendiente sobre el claim')
            if connection.execute(
                'SELECT 1 FROM evidence_links WHERE claim_id = ?', (claim_id,),
            ).fetchone() is None:
                raise KnowledgeConflict('El claim no conserva evidencia')
            if row['knowledge_state'] == state.value:
                return
            connection.execute(
                "UPDATE knowledge_claims SET knowledge_state = ?, revision = revision + 1, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE claim_id = ?", (state.value, claim_id),
            )
            connection.execute(
                'INSERT INTO claim_state_history(claim_id, revision, from_state, to_state, valid_from, actor, reason) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (claim_id, expected_revision + 1, row['knowledge_state'], state.value,
                 row['valid_from'], actor.strip(), reason.strip()),
            )
            connection.execute(
                "INSERT INTO events(event_type, message, details_json) VALUES "
                "('CLAIM_STATE_REVIEWED', 'Decisión de revisión de vigencia', ?)",
                (json.dumps({'claim_id': claim_id, 'actor': actor, 'state': state.value,
                             'revision': expected_revision + 1}),),
            )

    def succession(self, claim_id: int) -> list[KnowledgeClaim]:
        """Incluye predecesores y sucesores; UNION impide bucles en datos legacy."""
        from knowledge_orchestrator.repositories.semantic_repository.filas import _claim

        with closing(self.database.connect(readonly=True)) as connection:
            return [_claim(row) for row in connection.execute(
                'WITH RECURSIVE chain(id) AS (SELECT claim_id FROM knowledge_claims WHERE claim_id = ? '
                'UNION SELECT k.claim_id FROM knowledge_claims k JOIN chain c ON k.superseded_by = c.id '
                'UNION SELECT k.superseded_by FROM knowledge_claims k JOIN chain c ON k.claim_id = c.id '
                'WHERE k.superseded_by IS NOT NULL) '
                'SELECT k.* FROM knowledge_claims k JOIN chain c ON c.id = k.claim_id ORDER BY k.claim_id',
                (claim_id,),
            )]

    def evidence(self, claim_id: int) -> list[dict[str, object]]:
        with closing(self.database.connect(readonly=True)) as connection:
            return [dict(row) for row in connection.execute(
                'SELECT * FROM evidence_links WHERE claim_id = ? ORDER BY evidence_id', (claim_id,),
            )]

    @staticmethod
    def _pagination(limit: int, offset: int) -> None:
        if isinstance(limit, bool) or isinstance(offset, bool) or not 1 <= limit <= 1000 or offset < 0:
            raise ValueError('Paginación fuera de límites')
