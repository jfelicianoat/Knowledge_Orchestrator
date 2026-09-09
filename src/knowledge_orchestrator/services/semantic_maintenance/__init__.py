"""Mantenimiento semántico: extraer, comparar y aplicar con revisión humana.

La regla de oro es esta: el LLM puede proponer, pero no inventar ni aplicar.
Cada claim debe apuntar a un span local exacto y toda modificacion queda
pendiente de aprobacion humana antes de tocar una nota publicada.

El servicio está partido en tres:

- `contratos` — error y esquemas JSON estrictos.
- `prompts`   — lo que se le pide al modelo y cómo se envía.
- `analisis`  — cómo se lee la respuesta y cómo se escribe la nota.

Aquí queda la orquestación: qué se encola, en qué orden y con qué revisión.
"""
from __future__ import annotations

import difflib
import json
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from knowledge_orchestrator.domain.knowledge import KnowledgeConflict
from knowledge_orchestrator.domain.semantic_models import KnowledgeClaim, UpdateCandidate
from knowledge_orchestrator.integrations.obsidian_bridge import (
    NoteEditor,
    ObsidianBridgeUnavailable,
    UnconfiguredNoteEditor,
)
from knowledge_orchestrator.repositories.semantic_repository import SemanticRepository
from knowledge_orchestrator.services.maintenance_assessment import assess_proposal
from knowledge_orchestrator.services.maintenance_layout import plan_layout, valid_layout
from knowledge_orchestrator.services.provenance import source_provenance
from knowledge_orchestrator.services.semantic_maintenance.analisis import AnalisisMixin
from knowledge_orchestrator.services.semantic_maintenance.contratos import (
    COMPARISON_SCHEMA,
    EXTRACTION_SCHEMA,
    SemanticContractError,
)
from knowledge_orchestrator.services.semantic_maintenance.prompts import PromptsMixin

__all__ = [
    "COMPARISON_SCHEMA",
    "EXTRACTION_SCHEMA",
    "SemanticContractError",
    "SemanticMaintenanceService",
]


class SemanticMaintenanceService(PromptsMixin, AnalisisMixin):
    """Mantiene claims semanticos usando solo evidencia local verificable.

    La regla de oro es esta: el LLM puede proponer, pero no inventar ni aplicar.
    Cada claim debe apuntar a un span local exacto y toda modificacion queda pendiente
    de aprobacion humana antes de tocar una nota publicada.
    """

    def __init__(
        self,
        repository: SemanticRepository,
        *,
        checkpoint: Callable[[str], None] | None = None,
        note_editor: NoteEditor | None = None,
    ) -> None:
        self.repository = repository
        self.checkpoint = checkpoint or (lambda _name: None)
        self.note_editor = note_editor if note_editor is not None else UnconfiguredNoteEditor()

    def ingest_embedding_result(self, claim_id: int, model: str, payload: Mapping[str, Any]) -> None:
        if set(payload) != {"vector"} or not isinstance(payload["vector"], list):
            raise SemanticContractError("Resultado de embedding inválido")
        self.repository.record_embedding(claim_id, model, payload["vector"])

    def schedule_extraction(self, note_id: int) -> str:
        context = self.repository.note_context(note_id)
        if context["status"] != "PUBLISHED":
            raise SemanticContractError("Solo se puede analizar una nota publicada")
        document = Path(context["vault_path"]).read_text(encoding="utf-8")
        job_id = f"semantic_extract_note_{note_id}"
        request = self.broker_json_request(
            request_id=job_id,
            prompt=self.extraction_prompt(document, source_id=context["capture_id"]),
            schema=EXTRACTION_SCHEMA,
        )
        self.repository.create_job(
            job_id=job_id,
            kind="EXTRACT",
            note_id=note_id,
            candidate_id=None,
            idempotency_key=request["idempotency_key"],
            request=request,
        )
        return job_id

    def schedule_comparison(self, candidate_id: int) -> str:
        candidate = self.repository.get_candidate(candidate_id)
        if candidate is None:
            raise SemanticContractError("Candidato inexistente")
        target = self.repository.get_claim(candidate.target_claim_id)
        new_claim = self.repository.get_claim(candidate.new_claim_id)
        if target is None or new_claim is None:
            raise SemanticContractError("Faltan claims para comparar")
        job_id = f"semantic_compare_candidate_{candidate_id}"
        request = self.broker_json_request(
            request_id=job_id,
            prompt=self.comparison_prompt(
                old_claim=target.statement,
                new_claim=new_claim.statement,
                old_evidence=self.repository.evidence_quote(target.claim_id),
                new_evidence=self.repository.evidence_quote(new_claim.claim_id),
                source_context={'old': source_provenance(self.repository.database, target.source_capture_id),
                                'new': source_provenance(self.repository.database, new_claim.source_capture_id)},
            ),
            schema=COMPARISON_SCHEMA,
        )
        self.repository.create_job(
            job_id=job_id,
            kind="COMPARE",
            note_id=new_claim.note_id,
            candidate_id=candidate_id,
            idempotency_key=request["idempotency_key"],
            request=request,
        )
        return job_id

    def process_job_result(self, job, result_text: str) -> None:
        """Interpreta JSON del Broker y lo convierte en claims o candidatos revisables."""

        try:
            payload = json.loads(result_text)
        except json.JSONDecodeError as error:
            raise SemanticContractError("El Broker no devolvió JSON semántico estricto") from error
        if not isinstance(payload, Mapping):
            raise SemanticContractError("El resultado semántico debe ser un objeto JSON")
        if job.kind == "EXTRACT":
            if job.note_id is None:
                raise SemanticContractError("Job de extracción sin nota")
            for candidate_id in self.ingest_extraction(job.note_id, payload):
                self.schedule_comparison(candidate_id)
        elif job.kind == "COMPARE":
            if job.candidate_id is None:
                raise SemanticContractError("Job de comparación sin candidato")
            candidate = self.repository.get_candidate(job.candidate_id)
            if candidate is None:
                raise SemanticContractError("Candidato inexistente")
            if candidate.status == "PENDING_COMPARISON":
                self.compare(job.candidate_id, payload)
            elif candidate.status not in {"PENDING_REVIEW", "REJECTED", "APPLIED"}:
                raise SemanticContractError(f"El candidato quedó en estado {candidate.status}")
        else:
            raise SemanticContractError(f"Tipo de job no soportado: {job.kind}")

    def ingest_extraction(self, note_id: int, payload: Mapping[str, Any]) -> list[int]:
        context = self.repository.note_context(note_id)
        if context["status"] != "PUBLISHED":
            raise SemanticContractError("Solo se indexan notas publicadas")
        path = Path(context["vault_path"])
        document = path.read_text(encoding="utf-8")
        if self._hash_text(document) != context['content_hash']:
            raise SemanticContractError('La nota cambió externamente; requiere reconciliación')
        claims = self._parse_extraction(payload, document)
        created_candidates: list[int] = []
        for extracted in claims:
            new_claim = self.repository.add_claim(note_id, extracted, source_path=path)
            created_candidates.extend(self.generate_candidates(new_claim.claim_id))
        return sorted(set(created_candidates))

    def generate_candidates(self, new_claim_id: int) -> list[int]:
        new_claim = self.repository.get_claim(new_claim_id)
        if new_claim is None:
            raise SemanticContractError("Claim nuevo inexistente")
        if self.repository.note_context(new_claim.note_id)["status"] != "PUBLISHED":
            raise SemanticContractError("La evidencia nueva ya no está publicada")
        related = self.repository.find_related(new_claim)
        related_by_id = {claim.claim_id: (claim, reason) for claim, reason in related}
        for claim_id in self.repository.nearest_embeddings(new_claim.claim_id):
            if claim_id not in related_by_id:
                claim = self.repository.get_claim(claim_id)
                if claim and claim.note_id != new_claim.note_id and claim.topic_id == new_claim.topic_id \
                        and claim.source_capture_id != new_claim.source_capture_id:
                    related_by_id[claim_id] = (claim, "embedding")
        candidates: list[int] = []
        for target, reason in related_by_id.values():
            candidate = self.repository.create_candidate(target, new_claim, retrieval_reason=reason)
            candidates.append(candidate.candidate_id)
        return sorted(set(candidates))

    def compare(self, candidate_id: int, payload: Mapping[str, Any], *, expected_revision: int | None = None,
                actor: str = 'broker:comparison') -> UpdateCandidate:
        candidate = self.repository.get_candidate(candidate_id)
        if candidate is None:
            raise SemanticContractError("Candidato inexistente")
        target = self.repository.get_claim(candidate.target_claim_id)
        new_claim = self.repository.get_claim(candidate.new_claim_id)
        if target is None or new_claim is None:
            raise SemanticContractError("El candidato no conserva ambos claims")
        if self.repository.note_context(target.note_id)["status"] != "PUBLISHED" or \
                self.repository.note_context(new_claim.note_id)["status"] != "PUBLISHED":
            raise SemanticContractError("Los dos claims deben pertenecer a notas publicadas")
        decision = self._parse_comparison(payload)
        new_document = self._evidence_document(new_claim)
        new_quote = self.repository.evidence_quote(new_claim.claim_id)
        patch_json = None
        diff_text = None
        base_hash = None
        if decision.relation in {"EXTENDS", "CONTRADICTS", "SUPERSEDES"} and not target.manual_lock:
            if not decision.replacement_text or not decision.replacement_text.strip():
                raise SemanticContractError("La relación requiere replacement_text")
            context = self.repository.note_context(target.note_id)
            document = Path(context["vault_path"]).read_text(encoding="utf-8")
            base_hash = self._hash_text(document)
            if base_hash != context['content_hash']:
                raise SemanticContractError('La nota cambió externamente; requiere reconciliación')
            old_text = document[target.span_start:target.span_end]
            if not old_text:
                raise SemanticContractError("El span objetivo está vacío")
            replacement = decision.replacement_text.strip()
            if replacement != new_quote.strip():
                raise SemanticContractError('El texto propuesto debe conservar la evidencia nueva, sin inferencias')
            replacement = new_quote
            if old_text != self.repository.evidence_quote(target.claim_id):
                raise SemanticContractError('El span objetivo no conserva su evidencia')
            patch: dict = {
                "op": "replace",
                "start": target.span_start,
                "end": target.span_end,
                "old": old_text,
                "replacement": replacement,
                'source_note_id': new_claim.note_id,
                'source_hash': self._hash_text(new_document),
                'source_quote': new_quote,
            }
            patch = plan_layout(document, patch, claim_id=target.claim_id, body_start=self._body_start(document))
            patch_json = json.dumps(patch, ensure_ascii=False, sort_keys=True)
            diff_text = "".join(difflib.unified_diff(
                (patch['old'] + '\n').splitlines(keepends=True),
                (patch['replacement'] + '\n').splitlines(keepends=True),
                fromfile="current", tofile="proposed",
            ))
        return self.repository.record_comparison(
            candidate_id,
            decision,
            patch_json=patch_json,
            diff_text=diff_text,
            base_hash=base_hash,
            assessment=assess_proposal(self.repository, candidate, decision, target, new_claim, patch_json),
            expected_revision=expected_revision,
            actor=actor,
        )

    def proposal_detail(self, candidate_id: int) -> dict:
        candidate = self.repository.get_candidate(candidate_id)
        if candidate is None:
            raise LookupError('Propuesta inexistente')
        versions = self.repository.proposal_versions(candidate_id)
        return {'candidate_id': candidate_id, 'status': candidate.status, 'revision': candidate.proposal_revision,
                'reviewed_by': candidate.reviewed_by, 'applied_successor_id': candidate.applied_successor_id,
                'requires_regeneration': not versions, 'assessment': versions[-1]['snapshot'] if versions else None,
                'versions': versions,
                'automation_review': {
                    'status': 'POLICY_SIMULATION_REQUIRED', 'publication_authorized': False,
                    'selection': [{'candidate_id': candidate_id, 'expected_revision': candidate.proposal_revision}],
                    'message': 'La propuesta no evalúa políticas. Elige una política y simula esta revisión para '
                               'comprobar elegibilidad, bloqueos y cupos. Los registros históricos conservan '
                               'su evaluación original y no acreditan autorización actual.',
                }}

    def edit(self, candidate_id: int, payload: Mapping[str, Any], *, expected_revision: int,
             actor: str) -> UpdateCandidate:
        if not actor.strip():
            raise ValueError('La edición requiere actor')
        return self.compare(candidate_id, payload, expected_revision=expected_revision, actor=actor)

    def _evidence_document(self, claim: KnowledgeClaim) -> str:
        first_document = ''
        seen: set[int] = set()
        for _ in range(100):
            if claim.claim_id in seen:
                raise SemanticContractError('La procedencia contiene un ciclo')
            seen.add(claim.claim_id)
            context = self.repository.note_context(claim.note_id)
            if context['status'] != 'PUBLISHED':
                raise SemanticContractError('La evidencia ya no está publicada')
            try:
                document = Path(context['vault_path']).read_text(encoding='utf-8')
            except OSError as error:
                raise SemanticContractError('La evidencia no está disponible') from error
            if self._hash_text(document) != context['content_hash'] or \
                    document[claim.span_start:claim.span_end] != self.repository.evidence_quote(claim.claim_id):
                raise SemanticContractError('La evidencia cambió; requiere nueva comparación')
            if len(seen) == 1:
                first_document = document
            if claim.derived_from_claim_id is None:
                return first_document
            parent = self.repository.get_claim(claim.derived_from_claim_id)
            if parent is None or parent.status != 'ACTIVE' or parent.knowledge_state != 'CURRENT':
                raise SemanticContractError('La evidencia original de la proyección dejó de estar vigente')
            claim = parent
        raise SemanticContractError('Cadena de procedencia demasiado profunda')

    def _validate_new_evidence(self, candidate: UpdateCandidate, patch: dict) -> None:
        new_claim = self.repository.get_claim(candidate.new_claim_id)
        if new_claim is None or patch.get('source_note_id') != new_claim.note_id:
            raise SemanticContractError('La propuesta requiere una comparación con evidencia versionada')
        document = self._evidence_document(new_claim)
        if self._hash_text(document) != patch.get('source_hash') or \
                self.repository.evidence_quote(new_claim.claim_id) != patch.get('source_quote') or \
                not valid_layout(patch, claim_id=candidate.target_claim_id,
                                 old_quote=self.repository.evidence_quote(candidate.target_claim_id),
                                 new_quote=patch['source_quote']):
            raise SemanticContractError('La evidencia nueva cambió desde la comparación')

    def preview_application(self, candidate_id: int, *, expected_revision: int) -> dict:
        """Vista previa sin modificar candidato, eventos, revisiones ni archivos."""
        candidate = self.repository.get_candidate(candidate_id)
        result: dict = {'candidate_id': candidate_id, 'revision': expected_revision, 'eligible': False,
                        'blockers': [], 'target_note_id': None, 'target_claim_id': None,
                        'evidence_note_ids': [], 'action': 'Sin modificación'}
        if candidate is None:
            result['blockers'] = ['Propuesta inexistente']
            return result
        result.update(target_note_id=candidate.target_note_id, target_claim_id=candidate.target_claim_id,
                      relation=candidate.relation)
        try:
            if candidate.proposal_revision != expected_revision:
                raise KnowledgeConflict('La propuesta cambió desde que se abrió')
            if candidate.status != 'PENDING_REVIEW' or not candidate.patch_json:
                raise SemanticContractError('La propuesta requiere revisión o regeneración')
            context = self.repository.note_context(candidate.target_note_id)
            result['title'] = context['title']
            current = Path(context['vault_path']).read_text(encoding='utf-8')
            if self._hash_text(current) != candidate.base_hash:
                raise SemanticContractError('La nota cambió desde que se generó el diff')
            patch = self._validate_patch(candidate.patch_json, current)
            self._validate_new_evidence(candidate, patch)
            self.repository.inspect_application(candidate_id, base_hash=self._hash_text(current),
                                                patch_json=candidate.patch_json, expected_revision=expected_revision)
            claim = self.repository.get_claim(candidate.new_claim_id)
            seen: set[int] = set()
            while claim is not None and claim.claim_id not in seen and len(seen) < 100:
                seen.add(claim.claim_id)
                result['evidence_note_ids'].append(claim.note_id)
                claim = self.repository.get_claim(claim.derived_from_claim_id) if claim.derived_from_claim_id else None
            result.update(eligible=True, action='Actualizar nota, conservar histórico y reindexar sucesor',
                          before=patch['old'], proposed=patch['replacement'], title=context['title'],
                          assessment=next((version['snapshot'] for version in self.repository.proposal_versions(
                              candidate_id) if version['revision'] == expected_revision), None))
        except (ValueError, OSError) as error:
            result['blockers'] = [str(error) if isinstance(error, ValueError)
                                  else 'No se pudo leer la nota o evidencia']
        return result

    def approve(self, candidate_id: int, *, expected_revision: int | None = None,
                actor: str = 'human:review', review_batch_id: str | None = None,
                automation_run_id: str | None = None) -> UpdateCandidate:
        """Aplica un candidato aprobado solo si la nota sigue igual que cuando se hizo el diff."""

        candidate = self.repository.get_candidate(candidate_id)
        if candidate is None or candidate.status != "PENDING_REVIEW" or not candidate.patch_json:
            raise SemanticContractError("El candidato no está listo para aprobación")
        if expected_revision is not None and candidate.proposal_revision != expected_revision:
            raise KnowledgeConflict('La propuesta cambió desde que se abrió')
        if not actor.strip():
            raise ValueError('La aprobación requiere actor')
        context = self.repository.note_context(candidate.target_note_id)
        if context["status"] != "PUBLISHED":
            raise SemanticContractError("La nota objetivo ya no está publicada")
        path = Path(context["vault_path"])
        current = path.read_text(encoding="utf-8")
        try:
            if not candidate.base_hash or self._hash_text(current) != candidate.base_hash:
                raise SemanticContractError('La nota cambió desde que se generó el diff')
            patch = self._validate_patch(candidate.patch_json, current)
        except SemanticContractError:
            self.repository.mark_candidate(candidate_id, "CONFLICT", reason="NOTE_CHANGED_AFTER_DIFF",
                                           expected_status='PENDING_REVIEW',
                                           expected_revision=candidate.proposal_revision)
            raise
        try:
            self._validate_new_evidence(candidate, patch)
        except SemanticContractError:
            self.repository.mark_candidate(candidate_id, 'CONFLICT', reason='EVIDENCE_CHANGED_AFTER_DIFF',
                                           expected_status='PENDING_REVIEW',
                                           expected_revision=candidate.proposal_revision)
            raise
        updated = current[:patch["start"]] + patch["replacement"] + current[patch["end"]:]
        base_hash = self._hash_text(current)
        result_hash = self._hash_text(updated)
        temporary = path.with_name(f".{path.name}.semantic-{candidate_id}-{uuid.uuid4().hex}.tmp")
        prepared = self.repository.prepare_application(
            candidate_id,
            current_content=current,
            base_hash=base_hash,
            result_hash=result_hash,
            temp_path=temporary,
            patch_json=candidate.patch_json,
            expected_revision=candidate.proposal_revision,
            actor=actor,
            review_batch_id=review_batch_id,
            automation_run_id=automation_run_id,
        )
        # Este checkpoint garantiza que recovery conoce base_hash, result_hash y temporal.
        self.checkpoint("semantic_intent")
        if self._hash_text(path.read_text(encoding='utf-8')) != base_hash:
            self.repository.mark_candidate(candidate_id, 'CONFLICT', reason='NOTE_CHANGED_DURING_APPLICATION')
            raise SemanticContractError('La nota cambió durante la aprobación')
        try:
            self._validate_new_evidence(candidate, patch)
            self._materialize(path, temporary, updated, result_hash, expected_base_hash=base_hash)
        except SemanticContractError:
            self.repository.mark_candidate(candidate_id, 'CONFLICT', reason='CONTENT_CHANGED_DURING_APPLICATION')
            raise
        self.checkpoint("semantic_note_replaced")
        self.repository.mark_applied(candidate_id)
        return self.repository.get_candidate(candidate_id) or prepared

    def reject(self, candidate_id: int, *, expected_revision: int | None = None,
               actor: str = 'human:review', reason: str = 'Propuesta rechazada por el revisor') -> None:
        candidate = self.repository.get_candidate(candidate_id)
        if candidate is None or candidate.status not in {'PENDING_COMPARISON', 'PENDING_REVIEW', 'CONFLICT'}:
            raise SemanticContractError("El candidato no se puede rechazar")
        if not actor.strip() or not reason.strip():
            raise ValueError('La revisión requiere actor y motivo')
        self.repository.reject_candidate(candidate_id,
                                         expected_revision=candidate.proposal_revision if expected_revision is None
                                         else expected_revision, actor=actor, reason=reason)

    def recover(self) -> None:
        """Reanuda aplicaciones semanticas pendientes sin pisar cambios manuales."""

        self.repository.recover_jobs()
        for candidate in self.repository.list_candidates("APPLYING"):
            context = self.repository.note_context(candidate.target_note_id)
            path = Path(context["vault_path"])
            if not path.exists() or not candidate.base_hash or not candidate.result_hash or not candidate.patch_json:
                self.repository.mark_candidate(candidate.candidate_id, "ERROR", reason="INCOMPLETE_APPLICATION_INTENT")
                continue
            current = path.read_text(encoding="utf-8")
            current_hash = self._hash_text(current)
            if current_hash == candidate.result_hash:
                self.repository.mark_applied(candidate.candidate_id)
                continue
            if current_hash != candidate.base_hash:
                self.repository.mark_candidate(
                    candidate.candidate_id, "CONFLICT", reason="NOTE_CHANGED_DURING_RECOVERY"
                )
                continue
            original = self.repository.revision_content(candidate.candidate_id)
            patch = self._validate_patch(candidate.patch_json, original)
            updated = original[:patch["start"]] + patch["replacement"] + original[patch["end"]:]
            temporary = candidate.temp_path or path.with_name(f".{path.name}.semantic-{candidate.candidate_id}.tmp")
            try:
                if 'source_hash' in patch:
                    self._validate_new_evidence(candidate, patch)
                self._materialize(path, temporary, updated, candidate.result_hash,
                                  expected_base_hash=candidate.base_hash)
            except SemanticContractError:
                self.repository.mark_candidate(candidate.candidate_id, 'CONFLICT',
                                               reason='CONTENT_CHANGED_DURING_RECOVERY')
                continue
            except ObsidianBridgeUnavailable:
                # Preserve the durable intent until Obsidian becomes available.
                continue
            self.repository.mark_applied(candidate.candidate_id)
