"""Lectura del resultado del modelo y escritura segura de la nota.

La regla de oro del servicio se aplica aquí: el LLM puede proponer, pero no
inventar. Cada afirmación tiene que apuntar a un span local exacto, y el
parche se valida contra el contenido real antes de tocar nada.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

from knowledge_orchestrator.domain.semantic_models import ComparisonDecision, ExtractedClaim
from knowledge_orchestrator.services.filesystem import write_synced
from knowledge_orchestrator.services.semantic_maintenance.contratos import SemanticContractError


class AnalisisMixin:
    """Parseo del resultado del modelo y materialización del cambio."""

    @staticmethod
    def _parse_extraction(payload: Mapping[str, Any], document: str) -> list[ExtractedClaim]:
        if set(payload) != {"claims"} or not isinstance(payload.get("claims"), list):
            raise SemanticContractError("La extracción debe contener únicamente claims[]")
        body_start = AnalisisMixin._body_start(document)
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
            valid_start = isinstance(start, int) and not isinstance(start, bool)
            valid_end = isinstance(end, int) and not isinstance(end, bool)
            if not valid_start or not valid_end:
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
                valid = isinstance(value, str) and AnalisisMixin._valid_date(value)
                if value is not None and not valid:
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
