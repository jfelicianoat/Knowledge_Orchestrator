from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from knowledge_orchestrator.domain.semantic_models import ComparisonDecision, ExtractedClaim, UpdateCandidate
from knowledge_orchestrator.domain.broker_contracts import validate_create_task_request
from knowledge_orchestrator.repositories.semantic_repository import SemanticRepository

from .filesystem import write_synced


class SemanticContractError(ValueError):
    pass


EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["claims"],
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "statement", "claim_type", "volatility", "span_start", "span_end", "quote", "entities",
                ],
                "properties": {
                    "statement": {"type": "string"},
                    "claim_type": {"type": "string"},
                    "volatility": {"enum": ["LOW", "MEDIUM", "HIGH"]},
                    "span_start": {"type": "integer", "minimum": 0},
                    "span_end": {"type": "integer", "minimum": 1},
                    "quote": {"type": "string"},
                    "entities": {"type": "array", "items": {"type": "string"}},
                    "observed_at": {"type": ["string", "null"]},
                    "source_date": {"type": ["string", "null"]},
                    "manual_lock": {"type": "boolean"},
                },
            },
        }
    },
}


COMPARISON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["relation", "confidence", "impact", "rationale", "replacement_text"],
    "properties": {
        "relation": {"enum": ["SUPPORTS", "EXTENDS", "CONTRADICTS", "SUPERSEDES", "UNRELATED", "UNCERTAIN"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "impact": {"enum": ["LOW", "MEDIUM", "HIGH"]},
        "rationale": {"type": "string"},
        "replacement_text": {"type": ["string", "null"]},
    },
}


class SemanticMaintenanceService:
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

    @staticmethod
    def extraction_prompt(document: str, *, source_id: str) -> str:
        return (
            "Extrae únicamente afirmaciones verificables presentes literalmente en <document>. "
            "No uses conocimiento externo. Los offsets son índices Python sobre el documento completo y quote debe "
            "coincidir exactamente con document[span_start:span_end]. manual_lock solo será true cuando el documento "
            "lo marque explícitamente. Devuelve JSON que cumpla el schema indicado.\n\n"
            f"<source_id>{json.dumps(source_id, ensure_ascii=False)}</source_id>\n"
            f"<json_schema>{json.dumps(EXTRACTION_SCHEMA, ensure_ascii=False)}</json_schema>\n"
            f"<untrusted_document_json>{json.dumps(document, ensure_ascii=False)}</untrusted_document_json>"
        )

    @staticmethod
    def comparison_prompt(*, old_claim: str, new_claim: str, old_evidence: str, new_evidence: str) -> str:
        return (
            "Compara solo las dos afirmaciones y sus evidencias locales. No añadas hechos. Clasifica SUPPORTS, EXTENDS, "
            "CONTRADICTS, SUPERSEDES, UNRELATED o UNCERTAIN. replacement_text solo se usa para EXTENDS, CONTRADICTS "
            "o SUPERSEDES; en los demás casos debe ser null. Cuando se use, debe ser una sustitución "
            "autosuficiente respaldada por la evidencia nueva. Devuelve JSON conforme al schema.\n"
            f"<json_schema>{json.dumps(COMPARISON_SCHEMA, ensure_ascii=False)}</json_schema>\n"
            f"<old_claim_json>{json.dumps(old_claim, ensure_ascii=False)}</old_claim_json>"
            f"<old_evidence_json>{json.dumps(old_evidence, ensure_ascii=False)}</old_evidence_json>\n"
            f"<new_claim_json>{json.dumps(new_claim, ensure_ascii=False)}</new_claim_json>"
            f"<new_evidence_json>{json.dumps(new_evidence, ensure_ascii=False)}</new_evidence_json>"
        )

    @staticmethod
    def broker_json_request(
        *,
        request_id: str,
        prompt: str,
        schema: Mapping[str, Any],
        preferred_model: str | None = None,
        max_cost_usd: float | None = None,
    ) -> dict[str, Any]:
        request = {
            "idempotency_key": request_id,
            "request_id": request_id,
            "content": {"prompt": prompt, "attachments": [], "metadata": {"purpose": "semantic_maintenance"}},
            "output": {"format": "json", "json_schema": dict(schema), "language": "es"},
            "generation": {"temperature": 0.0, "max_output_tokens": 4000},
            "model_requirements": {
                "preferred_model": preferred_model,
                "fallback_allowed": True,
                "allowed_providers": ["ollama"],
                "cloud_allowed": False,
                "max_cost_usd": max_cost_usd,
            },
            "execution": {
                "strategy": "single", "preset": "fast", "scheduling": "sequential",
                "max_proposers": 1, "max_judges": 0, "max_rounds": 1, "timeout_seconds": 600,
                "early_stop": True,
                "selection": {
                    "mode": "auto", "diversity_policy": "different_families",
                    "arbiter_policy": "strongest_available", "allow_substitution": True,
                    "proposers": [], "required_proposers": [], "proposer_count": 1,
                },
            },
            "risk": {"data_classification": "local_only", "human_review_required": True},
            "priority": 100,
        }
        # Frontera semantica -> Broker: pedimos JSON estricto, local_only y revision humana.
        validate_create_task_request(request)
        return request

    @staticmethod
    def embedding_request(claim_id: int, statement: str, *, model: str | None = None) -> dict[str, Any]:
        schema = {
            "type": "object", "additionalProperties": False, "required": ["vector"],
            "properties": {"vector": {"type": "array", "minItems": 1, "items": {"type": "number"}}},
        }
        prompt = (
            "Genera una representación vectorial numérica para recuperación semántica local. "
            "Devuelve únicamente JSON conforme al schema: " + json.dumps(schema, ensure_ascii=False)
            + ". Texto no confiable: " + json.dumps(statement, ensure_ascii=False)
        )
        return SemanticMaintenanceService.broker_json_request(
            request_id=f"claim_embedding:{claim_id}", prompt=prompt, schema=schema, preferred_model=model,
        )

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
            patch = {
                "op": "replace",
                "start": target.span_start,
                "end": target.span_end,
                "old": old_text,
                "replacement": decision.replacement_text.strip(),
            }
            patch_json = json.dumps(patch, ensure_ascii=False, sort_keys=True)
            diff_text = "".join(difflib.unified_diff(
                [old_text + "\n"], [patch["replacement"] + "\n"],
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
                self.repository.mark_candidate(candidate.candidate_id, "CONFLICT", reason="NOTE_CHANGED_DURING_RECOVERY")
                continue
            original = self.repository.revision_content(candidate.candidate_id)
            patch = self._validate_patch(candidate.patch_json, original)
            updated = original[:patch["start"]] + patch["replacement"] + original[patch["end"]:]
            temporary = candidate.temp_path or path.with_name(f".{path.name}.semantic-{candidate.candidate_id}.tmp")
            self._materialize(path, temporary, updated, candidate.result_hash)
            self.repository.mark_applied(candidate.candidate_id)

    @staticmethod
    def _parse_extraction(payload: Mapping[str, Any], document: str) -> list[ExtractedClaim]:
        if set(payload) != {"claims"} or not isinstance(payload.get("claims"), list):
            raise SemanticContractError("La extracción debe contener únicamente claims[]")
        body_start = SemanticMaintenanceService._body_start(document)
        result: list[ExtractedClaim] = []
        allowed = {
            "statement", "claim_type", "volatility", "span_start", "span_end", "quote", "entities",
            "observed_at", "source_date", "manual_lock",
        }
        required = {"statement", "claim_type", "volatility", "span_start", "span_end", "quote", "entities"}
        for index, raw in enumerate(payload["claims"]):
            if not isinstance(raw, Mapping) or not required.issubset(raw) or set(raw) - allowed:
                raise SemanticContractError(f"Claim {index} no cumple el contrato")
            start, end = raw["span_start"], raw["span_end"]
            if not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int) or isinstance(end, bool):
                raise SemanticContractError(f"Claim {index} tiene offsets inválidos")
            # Sin quote exacta no hay evidencia; asi evitamos que el modelo cuele conocimiento externo.
            if start < body_start or end <= start or end > len(document) or document[start:end] != raw["quote"]:
                raise SemanticContractError(f"Claim {index} no está respaldado por su span local")
            statement = raw["statement"]
            entities = raw["entities"]
            claim_type = raw["claim_type"]
            quote = raw["quote"]
            if not isinstance(statement, str) or not statement.strip() or not isinstance(claim_type, str) \
                    or not claim_type.strip() or not isinstance(quote, str) or not isinstance(entities, list) or any(
                not isinstance(item, str) for item in entities
            ):
                raise SemanticContractError(f"Claim {index} tiene texto o entidades inválidos")
            volatility = raw["volatility"]
            if volatility not in {"LOW", "MEDIUM", "HIGH"}:
                raise SemanticContractError(f"Claim {index} tiene volatilidad inválida")
            manual_lock = raw.get("manual_lock", False)
            if not isinstance(manual_lock, bool):
                raise SemanticContractError(f"Claim {index} tiene manual_lock inválido")
            for field in ("observed_at", "source_date"):
                value = raw.get(field)
                if value is not None and (not isinstance(value, str) or not SemanticMaintenanceService._valid_date(value)):
                    raise SemanticContractError(f"Claim {index} tiene {field} inválido")
            result.append(ExtractedClaim(
                statement=statement.strip(), claim_type=claim_type.strip(), volatility=volatility,
                span_start=start, span_end=end, quote=raw["quote"], entities=tuple(entities),
                observed_at=raw.get("observed_at"), source_date=raw.get("source_date"),
                manual_lock=manual_lock,
            ))
        return result

    @staticmethod
    def _parse_comparison(payload: Mapping[str, Any]) -> ComparisonDecision:
        required = {"relation", "confidence", "impact", "rationale", "replacement_text"}
        if set(payload) != required:
            raise SemanticContractError("La comparación no cumple el contrato")
        relation = payload["relation"]
        confidence = payload["confidence"]
        impact = payload["impact"]
        rationale = payload["rationale"]
        if relation not in {"SUPPORTS", "EXTENDS", "CONTRADICTS", "SUPERSEDES", "UNRELATED", "UNCERTAIN"}:
            raise SemanticContractError("Relación inválida")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise SemanticContractError("Confianza inválida")
        if impact not in {"LOW", "MEDIUM", "HIGH"} or not isinstance(rationale, str) or not rationale.strip():
            raise SemanticContractError("Impacto o rationale inválido")
        replacement = payload["replacement_text"]
        if replacement is not None and not isinstance(replacement, str):
            raise SemanticContractError("replacement_text inválido")
        if relation in {"SUPPORTS", "UNRELATED", "UNCERTAIN"} and replacement is not None:
            raise SemanticContractError(f"{relation} no puede modificar contenido")
        return ComparisonDecision(relation, float(confidence), impact, rationale.strip(), replacement)

    @staticmethod
    def _validate_patch(patch_json: str, content: str) -> dict[str, Any]:
        try:
            patch = json.loads(patch_json)
        except json.JSONDecodeError as error:
            raise SemanticContractError("Patch JSON inválido") from error
        if set(patch) != {"op", "start", "end", "old", "replacement"} or patch["op"] != "replace":
            raise SemanticContractError("Operación de patch no permitida")
        start, end = patch["start"], patch["end"]
        if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start:
            raise SemanticContractError("Offsets de patch inválidos")
        if content[start:end] != patch["old"] or not isinstance(patch["replacement"], str):
            raise SemanticContractError("La nota cambió desde que se generó el diff")
        return patch

    @staticmethod
    def _body_start(document: str) -> int:
        if not document.startswith("---"):
            return 0
        match = re.search(r"\n---\s*\n", document[3:])
        return match.end() + 3 if match else len(document)

    @staticmethod
    def _materialize(path: Path, temporary: Path, content: str, expected_hash: str) -> None:
        write_synced(temporary, content.encode("utf-8"))
        path.parent.mkdir(parents=True, exist_ok=True)
        # La aplicacion ya tiene intencion durable; replace atomico evita notas a medio escribir.
        os.replace(temporary, path)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
            raise RuntimeError("El hash de la actualización semántica no coincide")

    @staticmethod
    def _hash_text(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _valid_date(value: str) -> bool:
        try:
            if "T" in value:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            else:
                date.fromisoformat(value)
            return True
        except ValueError:
            return False
