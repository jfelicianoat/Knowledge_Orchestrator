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
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from knowledge_orchestrator.domain.semantic_models import UpdateCandidate
from knowledge_orchestrator.repositories.semantic_repository import SemanticRepository
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
    ) -> None:
        self.repository = repository
        self.checkpoint = checkpoint or (lambda _name: None)

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
                if claim and claim.note_id != new_claim.note_id and claim.topic_id == new_claim.topic_id:
                    related_by_id[claim_id] = (claim, "embedding")
        candidates: list[int] = []
        for target, reason in related_by_id.values():
            candidate = self.repository.create_candidate(target, new_claim, retrieval_reason=reason)
            candidates.append(candidate.candidate_id)
        return sorted(set(candidates))

    def compare(self, candidate_id: int, payload: Mapping[str, Any]) -> UpdateCandidate:
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
        patch_json = None
        diff_text = None
        if decision.relation in {"EXTENDS", "CONTRADICTS", "SUPERSEDES"} and not target.manual_lock:
            if not decision.replacement_text or not decision.replacement_text.strip():
                raise SemanticContractError("La relación requiere replacement_text")
            context = self.repository.note_context(target.note_id)
            document = Path(context["vault_path"]).read_text(encoding="utf-8")
            old_text = document[target.span_start:target.span_end]
            if not old_text:
                raise SemanticContractError("El span objetivo está vacío")
            replacement = decision.replacement_text.strip()
            patch = {
                "op": "replace",
                "start": target.span_start,
                "end": target.span_end,
                "old": old_text,
                "replacement": replacement,
            }
            patch_json = json.dumps(patch, ensure_ascii=False, sort_keys=True)
            diff_text = "".join(difflib.unified_diff(
                [old_text + "\n"], [replacement + "\n"],
                fromfile="current", tofile="proposed",
            ))
        return self.repository.record_comparison(
            candidate_id,
            decision,
            patch_json=patch_json,
            diff_text=diff_text,
        )

    def approve(self, candidate_id: int) -> UpdateCandidate:
        """Aplica un candidato aprobado solo si la nota sigue igual que cuando se hizo el diff."""

        candidate = self.repository.get_candidate(candidate_id)
        if candidate is None or candidate.status != "PENDING_REVIEW" or not candidate.patch_json:
            raise SemanticContractError("El candidato no está listo para aprobación")
        context = self.repository.note_context(candidate.target_note_id)
        if context["status"] != "PUBLISHED":
            raise SemanticContractError("La nota objetivo ya no está publicada")
        path = Path(context["vault_path"])
        current = path.read_text(encoding="utf-8")
        try:
            patch = self._validate_patch(candidate.patch_json, current)
        except SemanticContractError:
            self.repository.mark_candidate(candidate_id, "CONFLICT", reason="NOTE_CHANGED_AFTER_DIFF")
            raise
        updated = current[:patch["start"]] + patch["replacement"] + current[patch["end"]:]
        base_hash = self._hash_text(current)
        result_hash = self._hash_text(updated)
        temporary = path.with_name(f".{path.name}.semantic-{candidate_id}.tmp")
        prepared = self.repository.prepare_application(
            candidate_id,
            current_content=current,
            base_hash=base_hash,
            result_hash=result_hash,
            temp_path=temporary,
            patch_json=candidate.patch_json,
        )
        # Este checkpoint garantiza que recovery conoce base_hash, result_hash y temporal.
        self.checkpoint("semantic_intent")
        self._materialize(path, temporary, updated, result_hash)
        self.checkpoint("semantic_note_replaced")
        self.repository.mark_applied(candidate_id)
        return self.repository.get_candidate(candidate_id) or prepared

    def reject(self, candidate_id: int) -> None:
        candidate = self.repository.get_candidate(candidate_id)
        if candidate is None or candidate.status not in {"PENDING_COMPARISON", "PENDING_REVIEW"}:
            raise SemanticContractError("El candidato no se puede rechazar")
        self.repository.mark_candidate(candidate_id, "REJECTED", reason="HUMAN_REJECTED")

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
            self._materialize(path, temporary, updated, candidate.result_hash)
            self.repository.mark_applied(candidate.candidate_id)
