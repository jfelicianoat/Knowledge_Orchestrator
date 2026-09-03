"""Lo que se le pide al modelo, y cómo se envuelve para el Broker.

Los prompts están juntos y aparte del servicio porque son la parte que se
toca al afinar resultados: se leen y se comparan sin bajar a la lógica de
aplicación.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from knowledge_orchestrator.domain.broker_contracts import validate_create_task_request
from knowledge_orchestrator.services.semantic_maintenance.contratos import (
    COMPARISON_SCHEMA,
    EXTRACTION_SCHEMA,
)


class PromptsMixin:
    """Construcción de prompts y de peticiones JSON estrictas."""

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
            "Compara solo las dos afirmaciones y sus evidencias locales. No añadas hechos. "
            "Clasifica SUPPORTS, EXTENDS, "
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
        return PromptsMixin.broker_json_request(
            request_id=f"claim_embedding:{claim_id}", prompt=prompt, schema=schema, preferred_model=model,
        )
