"""Lectura documental y recuperación de conocimiento con vigencia explícita."""
from __future__ import annotations

import hashlib
import json
import math
import re
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

from knowledge_orchestrator.domain.knowledge import KnowledgeConflict
from knowledge_orchestrator.repositories.knowledge_repository import KnowledgeRepository
from knowledge_orchestrator.services.knowledge import KnowledgeService
from knowledge_orchestrator.services.provenance import source_provenance


class KnowledgeAccess:
    def __init__(self, knowledge: KnowledgeService, vault: Path) -> None:
        self.knowledge = knowledge
        self.repository = knowledge.repository
        self.database = self.repository.database
        self.vault = vault

    def refresh(self) -> None:
        self.knowledge.reconcile()

    def claims(self, **filters) -> list[dict]:
        self.refresh()
        return [self.claim_payload(claim.claim_id, state=filters.get('state', 'current'))
                for claim in self.repository.claims(**filters)]

    def claim(self, claim_id: int, *, state: str = 'current') -> dict:
        self.refresh()
        clauses, args = self.repository.state_filter(state)
        with closing(self.database.connect(readonly=True)) as connection:
            row = connection.execute(
                'SELECT k.claim_id FROM knowledge_claims k WHERE k.claim_id = ? AND ' +
                ' AND '.join(clauses or ['1=1']), [claim_id, *args],
            ).fetchone()
        if row is None:
            raise LookupError('Claim no disponible en el estado solicitado')
        return self.claim_payload(claim_id, state=state)

    def claim_payload(self, claim_id: int, *, state: str = 'all') -> dict:
        clauses, parameters = self.repository.state_filter(state)
        with closing(self.database.connect(readonly=True)) as connection:
            row = connection.execute(
                'SELECT k.* FROM knowledge_claims k WHERE k.claim_id = ? AND ' +
                ' AND '.join(clauses or ['1=1']), [claim_id, *parameters],
            ).fetchone()
            if row is None:
                raise KnowledgeConflict('El claim cambió durante la consulta')
            payload = dict(row)
            payload['entities'] = json.loads(payload.pop('entities_json'))
            payload['manual_lock'] = bool(payload['manual_lock'])
            # El contrato externo expone vigencia; el estado operativo legacy se etiqueta por separado.
            payload['operational_status'] = payload.pop('status')
            payload['status'] = payload['knowledge_state']
            payload['entity_ids'] = [r[0] for r in connection.execute(
                'SELECT entity_id FROM claim_entities WHERE claim_id = ? ORDER BY entity_id', (claim_id,),
            )]
            payload['supersedes'] = [r[0] for r in connection.execute(
                'SELECT claim_id FROM knowledge_claims WHERE superseded_by = ? ORDER BY claim_id', (claim_id,),
            )]
        payload['evidence'] = [{k: v for k, v in evidence.items() if k != 'source_path'}
                               for evidence in self.repository.evidence(claim_id)]
        payload['sources'] = [self.source(source_id) for source_id in sorted({
            evidence['source_capture_id'] for evidence in payload['evidence']
        })]
        payload['verification'] = 'evidence_linked_not_independently_verified'
        return payload

    def entity_knowledge(self, entity_id: int, *, state: str = 'current', limit: int = 100, offset: int = 0) -> dict:
        entity = self.repository.entity(entity_id)
        if entity is None:
            raise LookupError('Entidad inexistente')
        return {'entity': asdict(entity), 'knowledge_state': state,
                'claims': self.claims(entity_id=entity_id, state=state, limit=limit, offset=offset)}

    def entity_history(self, entity_id: int, *, limit: int = 100, offset: int = 0) -> dict:
        payload = self.entity_knowledge(entity_id, state='historical', limit=limit, offset=offset)
        payload['transitions'] = {str(c['claim_id']): self.repository.history(c['claim_id']) for c in payload['claims']}
        ids = {c.claim_id for old in payload['claims'] for c in self.repository.succession(old['claim_id'])}
        payload['succession'] = [self.claim_payload(claim_id) for claim_id in sorted(ids)]
        return payload

    def source(self, capture_id: str) -> dict:
        return source_provenance(self.database, capture_id)

    def documents(self, *, limit: int = 100, offset: int = 0) -> list[dict]:
        KnowledgeRepository._pagination(limit, offset)
        self.refresh()
        with closing(self.database.connect(readonly=True)) as connection:
            return [dict(row) for row in connection.execute(
                'SELECT n.note_id AS document_id, n.capture_id, c.title, n.revision, n.status, '
                'n.content_hash, n.topic_id, n.published_at, r.state AS consistency '
                'FROM notes n JOIN captures c ON c.capture_id = n.capture_id '
                'LEFT JOIN knowledge_reconciliation r ON r.note_id = n.note_id '
                "WHERE n.status = 'PUBLISHED' ORDER BY n.note_id LIMIT ? OFFSET ?", (limit, offset),
            )]

    def document(self, document_id: int) -> dict:
        self.refresh()
        with closing(self.database.connect(readonly=True)) as connection:
            row = connection.execute(
                'SELECT n.*, c.title FROM notes n JOIN captures c ON c.capture_id = n.capture_id '
                "WHERE n.note_id = ? AND n.status = 'PUBLISHED'", (document_id,),
            ).fetchone()
        if row is None:
            raise LookupError('Documento publicado inexistente')
        path = Path(row['vault_path']).resolve()
        if not path.is_relative_to(self.vault.resolve()):
            raise KnowledgeConflict('El documento queda fuera de la bóveda configurada')
        try:
            content = path.read_bytes()
        except OSError as error:
            raise KnowledgeConflict('El documento no está disponible') from error
        if hashlib.sha256(content).hexdigest() != row['content_hash']:
            raise KnowledgeConflict('La nota cambió externamente; requiere reconciliación')
        return {'document_id': document_id, 'title': row['title'], 'revision': row['revision'],
                'content_hash': row['content_hash'], 'content': content.decode('utf-8'),
                'format': 'markdown', 'knowledge_state': 'mixed_document',
                'source': self.source(row['capture_id'])}

    def document_history(self, document_id: int, *, limit: int = 100, offset: int = 0) -> list[dict]:
        KnowledgeRepository._pagination(limit, offset)
        with closing(self.database.connect(readonly=True)) as connection:
            if not connection.execute('SELECT 1 FROM notes WHERE note_id = ?', (document_id,)).fetchone():
                raise LookupError('Documento inexistente')
            return [dict(row) for row in connection.execute(
                'SELECT revision, content_text AS content, content_hash, reason, candidate_id, created_at '
                'FROM note_revisions WHERE note_id = ? ORDER BY revision DESC LIMIT ? OFFSET ?',
                (document_id, limit, offset),
            )]

    def search(self, text: str, *, state: str = 'current', limit: int = 20, offset: int = 0) -> list[dict]:
        KnowledgeRepository._pagination(limit, offset)
        self.refresh()
        tokens = re.findall(r'\w+', text.casefold())[:32]
        if not tokens:
            return []
        expression = ' OR '.join('"' + token + '"' for token in tokens)
        clauses, args = self.repository.state_filter(state)
        with closing(self.database.connect(readonly=True)) as connection:
            ids = [r[0] for r in connection.execute(
                'SELECT k.claim_id FROM knowledge_claims_fts JOIN knowledge_claims k '
                'ON k.claim_id = knowledge_claims_fts.rowid WHERE knowledge_claims_fts MATCH ? AND ' +
                ' AND '.join(clauses or ['1=1']) + ' ORDER BY bm25(knowledge_claims_fts), k.claim_id LIMIT ? OFFSET ?',
                [expression, *args, limit, offset],
            )]
        return [self.claim_payload(claim_id, state=state) for claim_id in ids]

    def semantic_search(
        self, vector: list[float], model: str, *, state: str = 'current', limit: int = 20,
    ) -> list[dict]:
        """Recupera en el espacio del modelo declarado; nunca simula un embedding con búsqueda léxica."""
        KnowledgeRepository._pagination(limit, 0)
        if not vector or len(vector) > 8192 or not model.strip() or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in vector
        ):
            raise ValueError('Vector o modelo inválido')
        norm = math.hypot(*vector)
        if not norm or not math.isfinite(norm):
            raise ValueError('El vector no tiene una norma válida')
        self.refresh()
        clauses, args = self.repository.state_filter(state)
        with closing(self.database.connect(readonly=True)) as connection:
            rows = connection.execute(
                'SELECT k.claim_id, e.vector_json FROM claim_embeddings e '
                'JOIN knowledge_claims k ON k.claim_id = e.claim_id WHERE e.model = ? AND e.dimensions = ? AND ' +
                ' AND '.join(clauses or ['1=1']), [model, len(vector), *args],
            ).fetchall()
        ranked = []
        for row in rows:
            other = json.loads(row['vector_json'])
            if len(other) != len(vector) or any(not math.isfinite(v) for v in other):
                continue
            other_norm = math.hypot(*other)
            if other_norm and math.isfinite(other_norm):
                score = sum((a / norm) * (b / other_norm) for a, b in zip(vector, other, strict=True))
                ranked.append((score, row['claim_id']))
        return [{'score': score, 'claim': self.claim_payload(claim_id, state=state)}
                for score, claim_id in sorted(ranked, key=lambda item: (-item[0], item[1]))[:limit]]
