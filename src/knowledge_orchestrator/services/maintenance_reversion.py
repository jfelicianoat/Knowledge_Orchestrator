"""Reversión explícita con hash exacto, snapshot durable y recuperación antes de arrancar workers."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from knowledge_orchestrator.domain.knowledge import KnowledgeConflict
from knowledge_orchestrator.repositories.reversion_guards import text_hash
from knowledge_orchestrator.repositories.reversion_repository import ReversionRepository
from knowledge_orchestrator.services.semantic_maintenance import SemanticMaintenanceService


class MaintenanceReversionService:
    def __init__(self, repository: ReversionRepository, maintenance: SemanticMaintenanceService, *,
                 checkpoint: Callable[[str], None] | None = None) -> None:
        self.repository, self.maintenance = repository, maintenance
        self.checkpoint = checkpoint or (lambda _name: None)

    def preview(self, candidate_id: int, *, expected_revision: int, actor: str, key: str) -> dict:
        request = self.repository.request(candidate_id, expected_revision, actor, key)
        previous = self.repository.previous(actor, key, request)
        if previous:
            return previous
        plan = self.repository.inspect(candidate_id, expected_revision)
        self._documents(plan)
        return self.repository.create(plan, actor=actor, key=key, request=request)

    @staticmethod
    def _documents(plan: dict, *, replaced: bool = False) -> Path:
        documents = {}
        target = None
        for note in plan['notes']:
            path = Path(note['vault_path'])
            content = path.read_bytes().decode('utf-8')
            is_target = note['note_id'] == plan['note_id']
            expected = plan['result_hash'] if replaced and is_target else note['content_hash']
            if text_hash(content) != expected:
                raise KnowledgeConflict('Una nota cambió desde la vista previa de reversión')
            documents[note['note_id']] = plan['proposed'] if is_target else content
            if is_target:
                target = path
        for evidence in plan['evidence']:
            content = documents[evidence['source_note_id']]
            if not evidence['source_content_hash'] or text_hash(content) != evidence['source_content_hash'] \
                    or content[evidence['span_start']:evidence['span_end']] != evidence['quote']:
                raise KnowledgeConflict('La evidencia anterior no coincide con la revisión que se restauraría')
        for origin in plan['origins']:
            quote = next(link['quote'] for link in plan['evidence'] if link['claim_id'] == origin['claim_id'])
            content = documents[origin['note_id']]
            if content[origin['span_start']:origin['span_end']] != quote:
                raise KnowledgeConflict('La ubicación del claim anterior no coincide con su evidencia')
        if target is None:
            raise KnowledgeConflict('La reversión no identifica su nota destino')
        return target

    def confirm(self, identifier: str, *, actor: str, expected_plan_hash: str, reason: str) -> dict:
        record = self.repository.get(identifier, actor=actor)
        if record['status'] == 'PREVIEW':
            self._documents(record['plan'])
        record = self.repository.begin(identifier, actor=actor, plan_hash=expected_plan_hash, reason=reason)
        if record['status'] == 'APPLIED':
            return record
        self.checkpoint('reversion_intent')
        self._apply(record)
        return self.repository.get(identifier, actor=actor)

    def _apply(self, record: dict) -> None:
        identifier, plan = record['reversion_id'], record['plan']
        try:
            note = next(note for note in plan['notes'] if note['note_id'] == plan['note_id'])
            path = Path(note['vault_path'])
            current_hash = text_hash(path.read_bytes().decode('utf-8'))
            replaced = current_hash == plan['result_hash']
            self._documents(plan, replaced=replaced)
            if not replaced:
                temporary = path.with_name(f'.{path.name}.reversion-{identifier}.tmp')
                self.maintenance._materialize(path, temporary, plan['proposed'], plan['result_hash'],
                                              expected_base_hash=plan['base_hash'])
            self.checkpoint('reversion_note_replaced')
            self._documents(plan, replaced=True)
            self.repository.finish(identifier)
        except (ValueError, OSError):
            # Las diferencias de contenido/estado son conflictos; un error SQLite deja la intención recuperable.
            self.repository.conflict(identifier, 'REVERSION_CONTENT_OR_STATE_CHANGED')
            raise

    def recover(self) -> None:
        for record in self.repository.pending():
            try:
                self._apply(record)
            except (ValueError, OSError):
                continue
