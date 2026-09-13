"""Lectura del resultado del modelo y escritura segura de la nota.

La regla de oro del servicio se aplica aquí: el LLM puede proponer, pero no
inventar. Cada afirmación tiene que apuntar a un span local exacto, y el
parche se valida contra el contenido real antes de tocar nada.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

from knowledge_orchestrator.domain.semantic_models import ComparisonDecision, ExtractedClaim
from knowledge_orchestrator.integrations.obsidian_bridge import NoteEditor, ObsidianBridgeConflict
from knowledge_orchestrator.services.maintenance_layout import history_boundary
from knowledge_orchestrator.services.semantic_maintenance.contratos import SemanticContractError


def locate_quote(document: str, quote: str, *, body_start: int) -> tuple[int, int] | None:
    """Localiza la cita en el documento y devuelve sus offsets reales.

    Contar caracteres es lo único que un modelo no puede hacer: ve tokens, no
    índices. Contra el Broker real, dos modelos distintos (`lfm2:24b` y
    `nemotron:latest`) extrajeron las afirmaciones correctas y las acompañaron de
    spans inventados —(0,79), (80,119), (120,169): tramos consecutivos que no
    correspondían a nada—, así que exigirles `document[span_start:span_end] ==
    quote` era pedir algo inalcanzable y ninguna afirmación llegaba nunca al
    conocimiento. Localizar la cita es trabajo de la aplicación, que sí sabe
    contar; el modelo solo tiene que copiar texto.

    La garantía no se relaja: si la cita no aparece en el documento, se devuelve
    `None` y quien llama la rechaza. Se intenta primero la coincidencia exacta y
    después una con espacios normalizados, porque el modelo devuelve los
    renglones unidos por un espacio donde el documento tiene un salto de línea.
    """

    if not quote.strip():
        return None
    exact = document.find(quote, body_start)
    if exact != -1:
        return exact, exact + len(quote)
    # Índice del documento sin espacios repetidos, guardando a qué posición real
    # corresponde cada carácter conservado para poder devolver offsets reales.
    compact: list[str] = []
    origins: list[int] = []
    previous_blank = True
    for position in range(body_start, len(document)):
        character = document[position]
        if character.isspace():
            if previous_blank:
                continue
            compact.append(" ")
            origins.append(position)
            previous_blank = True
            continue
        compact.append(character)
        origins.append(position)
        previous_blank = False
    needle = " ".join(quote.split())
    found = "".join(compact).find(needle)
    if found == -1 or not needle:
        return None
    start = origins[found]
    end = origins[found + len(needle) - 1] + 1
    return start, end


def _offered_span(document: str, raw: Mapping[str, Any], *, body_start: int, index: int) -> tuple[int, int] | None:
    """Los offsets del modelo, solo si resultan ser ciertos.

    Se siguen respetando cuando aciertan: con dos ocurrencias idénticas de la
    misma cita en un documento, son lo único que distingue a cuál se refiere.
    """

    start, end = raw.get("span_start"), raw.get("span_end")
    for value in (start, end):
        if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
            raise SemanticContractError(f"Claim {index} tiene offsets inválidos")
    if not isinstance(start, int) or not isinstance(end, int):
        return None
    if start < body_start or end <= start or end > len(document) or document[start:end] != raw["quote"]:
        return None
    return start, end


class AnalisisMixin:
    """Parseo del resultado del modelo y materialización del cambio."""

    note_editor: NoteEditor

    @staticmethod
    def _parse_extraction(payload: Mapping[str, Any], document: str) -> list[ExtractedClaim]:
        if set(payload) != {"claims"} or not isinstance(payload.get("claims"), list):
            raise SemanticContractError("La extracción debe contener únicamente claims[]")
        body_start = AnalisisMixin._body_start(document)
        historical_start = history_boundary(document)
        result: list[ExtractedClaim] = []
        allowed = {
            "statement", "claim_type", "volatility", "span_start", "span_end", "quote", "entities",
            "observed_at", "source_date", "manual_lock",
        }
        required = {"statement", "claim_type", "volatility", "quote", "entities"}
        for index, raw in enumerate(payload["claims"]):
            if not isinstance(raw, Mapping) or not required.issubset(raw) or set(raw) - allowed:
                raise SemanticContractError(f"Claim {index} no cumple el contrato")
            if not isinstance(raw["quote"], str):
                raise SemanticContractError(f"Claim {index} tiene texto o entidades inválidos")
            # Los offsets del modelo se aceptan solo si resultan ser ciertos; en
            # cuanto no cuadran, manda la cita y los calcula la aplicación.
            span = _offered_span(document, raw, body_start=body_start, index=index)
            if span is None:
                span = locate_quote(document, raw["quote"], body_start=body_start)
            # Sin cita localizable no hay evidencia: así el modelo no cuela
            # conocimiento externo ni citas que el documento no contiene.
            if span is None:
                raise SemanticContractError(f"Claim {index} no está respaldado por su span local")
            start, end = span
            if historical_start is not None:
                if start >= historical_start:
                    continue  # El contenido histórico no se reintroduce como conocimiento vigente.
                if end > historical_start:
                    raise SemanticContractError('El span mezcla conocimiento vigente e histórico')
            statement = raw["statement"]
            entities = raw["entities"]
            claim_type = raw["claim_type"]
            quote = raw["quote"]
            if not isinstance(statement, str) or not statement.strip() or not isinstance(claim_type, str) \
                    or not claim_type.strip() or not isinstance(quote, str) or not isinstance(entities, list) or any(
                not isinstance(item, str) for item in entities
            ):
                raise SemanticContractError(f"Claim {index} tiene texto o entidades inválidos")
            if " ".join(statement.split()) != " ".join(quote.split()):
                raise SemanticContractError(f'Claim {index}: statement debe conservar la cita, sin añadir inferencias')
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
            # La evidencia guardada es el texto del documento, no la versión del
            # modelo —que une los renglones con un espacio—: lo que se compara
            # después (parches, deriva, procedencia) exige que
            # `document[span_start:span_end]` sea exactamente la cita. El
            # statement del modelo ya se validó arriba contra su propia cita, así
            # que esto normaliza espacios sin dejar pasar nada inventado.
            evidence = document[start:end]
            result.append(ExtractedClaim(
                statement=evidence, claim_type=claim_type.strip(), volatility=volatility,
                span_start=start, span_end=end, quote=evidence, entities=tuple(entities),
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
        required = {'op', 'start', 'end', 'old', 'replacement'}
        allowed = required | {'source_note_id', 'source_hash', 'source_quote', 'history_strategy', 'current_offset'}
        if not isinstance(patch, dict) or not required <= set(patch) or set(patch) - allowed \
                or patch['op'] != 'replace':
            raise SemanticContractError("Operación de patch no permitida")
        start, end = patch["start"], patch["end"]
        if type(start) is not int or type(end) is not int or start < AnalisisMixin._body_start(content) \
                or end <= start or end > len(content):
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

    def _materialize(self, path: Path, temporary: Path, content: str, expected_hash: str,
                     *, expected_base_hash: str | None = None) -> None:
        if expected_base_hash is None:
            raise SemanticContractError('La publicación requiere una base versionada')
        # temp_path is the persisted identity of the intent, including a UUID for
        # new approvals. No temporary note is written by the Orchestrator anymore.
        identity = [str(temporary.resolve()).replace('\\', '/').lower(), expected_base_hash, expected_hash]
        request_id = self._hash_text(json.dumps(identity, ensure_ascii=False))
        try:
            self.note_editor.replace(path, content, base_hash=expected_base_hash,
                                     result_hash=expected_hash, request_id=request_id)
        except ObsidianBridgeConflict:
            raise SemanticContractError('La nota o el recibo de Obsidian requieren revisión') from None

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
