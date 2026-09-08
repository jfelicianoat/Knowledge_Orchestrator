"""Aprobación humana de un plan congelado, con recuperación y resultado por tarea."""
from __future__ import annotations

import re
from collections.abc import Callable
from contextlib import closing

from knowledge_orchestrator.repositories.review_batch_repository import ReviewBatchRepository, encoded
from knowledge_orchestrator.services.semantic_maintenance import SemanticMaintenanceService

MAX_BATCH_ITEMS = 1000


class ReviewBatchService:
    def __init__(self, repository: ReviewBatchRepository, maintenance: SemanticMaintenanceService, *,
                 checkpoint: Callable[[str], None] | None = None) -> None:
        self.repository, self.maintenance = repository, maintenance
        self.checkpoint = checkpoint or (lambda _name: None)

    def preview(self, *, owner: str, key: str, selection: list[dict] | None = None) -> dict:
        if not owner.strip() or not re.fullmatch(r'[A-Za-z0-9_.:-]{8,200}', key):
            raise ValueError('El lote requiere actor y clave idempotente')
        if selection is not None:
            if not 1 <= len(selection) <= MAX_BATCH_ITEMS:
                raise ValueError('Selecciona entre 1 y 1000 propuestas por lote')
            for item in selection:
                if set(item) != {'candidate_id', 'expected_revision'} or type(item['candidate_id']) is not int \
                        or item['candidate_id'] <= 0 or type(item['expected_revision']) is not int \
                        or item['expected_revision'] < 0:
                    raise ValueError('Selección de propuestas inválida')
            if len({item['candidate_id'] for item in selection}) != len(selection):
                raise ValueError('Una propuesta no puede repetirse en la selección')
            selection = sorted(selection, key=lambda item: item['candidate_id'])
        request = {'selection': selection}
        existing = self.repository.existing(owner, key, request)
        if existing is not None:
            return existing
        if selection is None:
            with closing(self.repository.database.connect(readonly=True)) as connection:
                selection = [dict(row) for row in connection.execute(
                    'SELECT candidate_id,proposal_revision AS expected_revision FROM update_candidates '
                    "WHERE status IN ('PENDING_COMPARISON','PENDING_REVIEW','CONFLICT') "
                    'ORDER BY candidate_id LIMIT ?', (MAX_BATCH_ITEMS + 1,))]
            if len(selection) > MAX_BATCH_ITEMS:
                raise ValueError('Hay más de 1000 propuestas; selecciona un lote para revisarlo')
        items, size = [], 0
        for selected in selection:
            item = self.maintenance.preview_application(selected['candidate_id'],
                                                        expected_revision=selected['expected_revision'])
            size += len(encoded(item).encode())
            if size > 8 * 1024 * 1024:
                raise ValueError('La vista previa supera 8 MiB; divide la selección en lotes menores')
            items.append(item)
        eligible = [item for item in items if item['eligible']]
        for index, item in enumerate(eligible):
            for other in eligible[index + 1:]:
                if item['target_note_id'] == other['target_note_id'] \
                        or item['target_note_id'] in other['evidence_note_ids'] \
                        or other['target_note_id'] in item['evidence_note_ids']:
                    for dependent in (item, other):
                        dependent['eligible'] = False
                        reason = 'Estas propuestas dependen de una misma nota; revísalas por separado'
                        if reason not in dependent['blockers']:
                            dependent['blockers'].append(reason)
        applicable = [item for item in items if item['eligible']]
        plan = {'items': items, 'counts': {'tasks': len(items), 'eligible_tasks': len(applicable),
                                         'ineligible_tasks': len(items) - len(applicable),
                                         'existing_claims': len({item['target_claim_id'] for item in applicable}),
                                         'new_claims': len(applicable),
                                         'notes': len({item['target_note_id'] for item in applicable})},
                'mode': 'all_eligible' if request['selection'] is None else 'selected',
                'authorization': 'explicit_human_confirmation_required'}
        return self.repository.create(owner=owner, key=key, request=request, plan=plan)

    def run_next(self) -> bool:
        batch = self.repository.claim_next()
        if batch is None:
            return False
        try:
            self._run_batch(batch)
        except Exception:
            self.repository.pause_for_recovery(batch['batch_id'])
            raise
        return True

    def _run_batch(self, batch: dict) -> None:
        batch_id, owner = batch['batch_id'], batch['owner']
        for item in batch['items']:
            if item['status'] != 'PENDING':
                continue
            candidate_id = item['candidate_id']
            self.repository.start_item(batch_id, candidate_id)
            self.checkpoint('batch_item_started')
            candidate = self.maintenance.repository.get_candidate(candidate_id)
            status: str
            result: dict
            if candidate is not None and candidate.review_batch_id == batch_id and candidate.status == 'APPLYING':
                # Recuperación al arrancar resolverá la intención; no competir con una escritura viva.
                self.repository.pause_for_recovery(batch_id)
                return
            if candidate is not None and candidate.review_batch_id == batch_id and candidate.status == 'APPLIED':
                status, result = 'APPLIED', {'successor_id': candidate.applied_successor_id, 'recovered': True}
            elif candidate is None or candidate.status in {'APPLIED', 'REJECTED', 'APPLYING'}:
                status, result = 'EXTERNALLY_RESOLVED', {'reason': 'La propuesta fue resuelta o tomada fuera del lote'}
            else:
                try:
                    applied = self.maintenance.approve(candidate_id, expected_revision=item['expected_revision'],
                                                        actor=owner, review_batch_id=batch_id)
                    status, result = 'APPLIED', {'successor_id': applied.applied_successor_id}
                except Exception as error:
                    current = self.maintenance.repository.get_candidate(candidate_id)
                    if current is not None and current.status == 'APPLYING':
                        self.repository.pause_for_recovery(batch_id)
                        return
                    status = 'CONFLICT' if isinstance(error, ValueError) else 'FAILED'
                    reason = str(error) if isinstance(error, ValueError) else 'Fallo al aplicar la propuesta'
                    result = {'reason': reason}
            self.checkpoint('batch_item_applied_before_receipt')
            self.repository.finish_item(batch_id, candidate_id, status=status, result=result)
        self.repository.finish_batch(batch_id)
