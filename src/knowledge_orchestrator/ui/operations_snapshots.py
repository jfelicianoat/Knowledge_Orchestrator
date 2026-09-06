"""Lecturas acotadas para explorar conocimiento; comparte vigencia con la API."""
from __future__ import annotations

from contextlib import closing

from knowledge_orchestrator.repositories.database import Database
from knowledge_orchestrator.repositories.knowledge_repository import KnowledgeRepository
from knowledge_orchestrator.repositories.semantic_repository.filas import normalize_text
from knowledge_orchestrator.services.knowledge import KnowledgeService

PENDING_PROPOSALS = "s.status IN ('PENDING_COMPARISON','PENDING_REVIEW','CONFLICT','APPLYING')"


class OperationsSnapshots:
    def __init__(self, database: Database) -> None:
        self.database = database

    def refresh_knowledge(self, **filters) -> dict:
        """Usar desde un worker: contrasta archivos antes de mostrar vigencia."""
        KnowledgeService(KnowledgeRepository(self.database)).reconcile()
        snapshot = self.knowledge(**filters)
        if snapshot['offset'] and snapshot['offset'] >= snapshot['total']:
            offset = max(0, ((snapshot['total'] - 1) // snapshot['limit']) * snapshot['limit'])
            snapshot = self.knowledge(**{**filters, 'offset': offset})
        return snapshot

    def knowledge(self, *, state: str = 'current', query: str = '', limit: int = 100,
                  offset: int = 0) -> dict:
        KnowledgeRepository._pagination(limit, offset)
        if len(query) > 4000:
            raise ValueError('La búsqueda admite como máximo 4000 caracteres')
        args: list[object]
        if state == 'review':
            clauses, args = ["k.knowledge_state IN ('DISPUTED','UNCERTAIN','REVIEW_REQUIRED')"], []
        else:
            clauses, args = KnowledgeRepository.state_filter(state)
        if query.strip():
            clauses.append('(instr(k.normalized_statement,?)>0 OR EXISTS ('
                           'SELECT 1 FROM claim_entities ce JOIN knowledge_entities e USING(entity_id) '
                           'WHERE ce.claim_id=k.claim_id AND instr(lower(e.name),lower(?))>0))')
            args.extend([normalize_text(query.strip()), query.strip()])
        where = ' AND '.join(clauses or ['1=1'])
        current_clauses, current_args = KnowledgeRepository.state_filter('current')
        current_sql = ' AND '.join(current_clauses)
        with closing(self.database.connect(readonly=True)) as connection:
            connection.execute('BEGIN')
            total = connection.execute('SELECT count(*) FROM knowledge_claims k WHERE ' + where, args).fetchone()[0]
            rows = connection.execute(
                'SELECT k.claim_id,k.note_id,k.statement,k.knowledge_state,k.manual_lock,k.revision,'
                'k.derived_from_claim_id,k.superseded_by,c.title,n.vault_path,('
                + current_sql + ') AS available_current '
                'FROM knowledge_claims k JOIN notes n ON n.note_id=k.note_id '
                'JOIN captures c ON c.capture_id=n.capture_id WHERE ' + where
                + ' ORDER BY k.claim_id DESC LIMIT ? OFFSET ?', [*current_args, *args, limit, offset]).fetchall()
            return {'total': total, 'items': [dict(row) for row in rows], 'offset': offset, 'limit': limit}

    def counts(self) -> dict[str, int]:
        clauses, args = KnowledgeRepository.state_filter('current')
        with closing(self.database.connect(readonly=True)) as connection:
            connection.execute('BEGIN')
            current = connection.execute('SELECT count(*) FROM knowledge_claims k WHERE ' + ' AND '.join(clauses),
                                         args).fetchone()[0]
            queries = {
                'historical': "SELECT count(*) FROM knowledge_claims WHERE knowledge_state "
                              "IN ('HISTORICAL','SUPERSEDED')",
                'review': "SELECT count(*) FROM knowledge_claims WHERE knowledge_state IN "
                          "('DISPUTED','UNCERTAIN','REVIEW_REQUIRED')",
                'sources': "SELECT count(*) FROM monitored_sources WHERE json_extract(config_json,'$.enabled')=1",
                'changes': "SELECT count(*) FROM source_changes WHERE status IN ('REVIEW','READY')",
                'analysis': "SELECT count(*) FROM semantic_jobs WHERE status "
                            "IN ('READY','SUBMITTING','QUEUED','PROCESSING')",
                'proposals': 'SELECT count(*) FROM update_candidates s WHERE ' + PENDING_PROPOSALS,
                'applied': "SELECT count(*) FROM update_candidates WHERE status='APPLIED'",
                'contradictions': "SELECT count(*) FROM update_candidates WHERE relation='CONTRADICTS' "
                                  "AND status IN ('PENDING_REVIEW','CONFLICT','APPLYING')",
                'source_errors': 'SELECT count(*) FROM monitored_sources WHERE failures>0',
            }
            return {'current': current, **{key: connection.execute(sql).fetchone()[0] for key, sql in queries.items()}}

    def refresh_counts(self) -> dict[str, int]:
        KnowledgeService(KnowledgeRepository(self.database)).reconcile()
        return self.counts()

    def flow(self, kind: str, *, scope: str = 'pending', limit: int = 100, offset: int = 0) -> dict:
        """Etapas reales del pipeline, sin cargar prompts ni resultados privados del Broker."""
        KnowledgeRepository._pagination(limit, offset)
        if scope not in {'pending', 'errors', 'all'}:
            raise ValueError('Filtro de operaciones inválido')
        if kind == 'changes':
            source = ('source_changes s JOIN monitored_sources m ON m.source_id=s.source_id '
                      'LEFT JOIN api_ingestions i ON i.ingestion_id=s.ingestion_id '
                      'LEFT JOIN captures c ON c.capture_id=i.capture_id')
            fields = ("s.change_id AS id,s.title,s.status,s.observed_at AS updated,s.source_id,i.capture_id,"
                      "json_extract(m.config_json,'$.name') AS source_name,c.status AS capture_status,"
                      's.delivery_error AS error_code')
            clauses = {'pending': "s.status IN ('REVIEW','READY')",
                       'errors': 's.delivery_error IS NOT NULL', 'all': '1=1'}
            order = 's.observed_at DESC,s.change_id'
        elif kind == 'analysis':
            source = 'semantic_jobs s LEFT JOIN notes n ON n.note_id=s.note_id LEFT JOIN captures c USING(capture_id)'
            fields = ("s.job_id AS id,COALESCE(c.title,'Análisis') AS title,s.status,s.updated_at AS updated,"
                      's.kind,s.candidate_id,s.broker_task_id,s.error_code,n.capture_id,s.attempt')
            clauses = {'pending': "s.status IN ('READY','SUBMITTING','QUEUED','PROCESSING')",
                       'errors': "s.status='ERROR'", 'all': '1=1'}
            order = 's.updated_at DESC,s.job_id'
        elif kind in {'proposals', 'history'}:
            source = 'update_candidates s JOIN notes n ON n.note_id=s.target_note_id JOIN captures c USING(capture_id)'
            fields = ('s.candidate_id AS id,c.title,s.status,s.updated_at AS updated,s.relation,s.rationale,'
                      's.blocked_reason AS error_code,n.capture_id,s.target_note_id,s.reviewed_by,s.proposal_revision')
            clauses = {'pending': PENDING_PROPOSALS,
                       'errors': "s.status IN ('ERROR','CONFLICT')", 'all': '1=1'}
            if kind == 'history':
                clauses = {'pending': '0=1', 'errors': '0=1', 'all': "s.status IN ('APPLIED','REJECTED')"}
            order = 's.updated_at DESC,s.candidate_id DESC'
        elif kind == 'activity':
            source = 'events s'
            fields = ('s.event_id AS id,s.message AS title,s.event_type AS status,s.created_at AS updated')
            clauses = dict.fromkeys(('pending', 'all'), '1=1')
            clauses['errors'] = "s.event_type LIKE '%ERROR%' OR s.event_type LIKE '%FAILED%'"
            order = 's.created_at DESC,s.event_id DESC'
        else:
            raise ValueError('Etapa inexistente')
        with closing(self.database.connect(readonly=True)) as connection:
            connection.execute('BEGIN')
            total = connection.execute('SELECT count(*) FROM ' + source + ' WHERE ' + clauses[scope]).fetchone()[0]
            offset = min(offset, max(0, ((total - 1) // limit) * limit))
            rows = connection.execute('SELECT ' + fields + ' FROM ' + source + ' WHERE ' + clauses[scope]
                                      + ' ORDER BY ' + order + ' LIMIT ? OFFSET ?', (limit, offset)).fetchall()
            return {'items': [dict(row) for row in rows], 'total': total, 'offset': offset, 'limit': limit}

    def change_flow(self, change_id: str) -> dict:
        with closing(self.database.connect(readonly=True)) as connection:
            row = connection.execute(
                'SELECT s.change_id,s.source_id,i.capture_id,i.status AS delivery_status,c.status AS capture_status '
                'FROM source_changes s LEFT JOIN api_ingestions i ON i.ingestion_id=s.ingestion_id '
                'LEFT JOIN captures c ON c.capture_id=i.capture_id WHERE s.change_id=?', (change_id,)).fetchone()
            if row is None:
                raise LookupError('La novedad no existe')
            result = dict(row)
            result['note_ids'] = [item[0] for item in connection.execute('SELECT note_id FROM notes WHERE capture_id=?',
                                                                        (row['capture_id'],))]
            result['candidate_ids'] = [item[0] for item in connection.execute(
                'SELECT DISTINCT u.candidate_id FROM update_candidates u '
                'JOIN knowledge_claims k ON k.claim_id=u.new_claim_id WHERE k.source_capture_id=? '
                'ORDER BY u.candidate_id', (row['capture_id'],))]
            return result
