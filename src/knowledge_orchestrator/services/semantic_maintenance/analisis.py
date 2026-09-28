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
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast

from knowledge_orchestrator.domain.semantic_models import (
    ComparisonDecision,
    ExtractedClaim,
    Impact,
    SourceEvidence,
)
from knowledge_orchestrator.integrations.obsidian_bridge import NoteEditor, ObsidianBridgeConflict
from knowledge_orchestrator.services.maintenance_layout import history_boundary
from knowledge_orchestrator.services.semantic_maintenance.contratos import SemanticContractError
from knowledge_orchestrator.services.semantic_maintenance.segmentos import (
    find_support,
    note_segments,
    source_segments,
)


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


@dataclass(frozen=True, slots=True)
class ExtractionReport:
    claims: list[ExtractedClaim]
    ignored_source_links: int = 0
    unknown_note_segments: int = 0

    def support_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for claim in self.claims:
            counts[claim.source_support] = counts.get(claim.source_support, 0) + 1
        return counts


_SEGMENT_ALLOWED = {
    "note_segment", "source_segments", "claim_type", "volatility", "entities",
    "observed_at", "source_date", "manual_lock",
}
_LEGACY_ALLOWED = {
    "statement", "claim_type", "volatility", "span_start", "span_end", "quote", "entities",
    "observed_at", "source_date", "manual_lock",
}


def _validated_fields(raw: Mapping[str, Any], index: int) -> dict[str, Any]:
    """Comprueba claves y TIPOS antes de usar ningún valor (auditoría H04).

    `volatility: []` llegaba a `volatility in {...}` y reventaba con un
    `TypeError` (una lista no es hashable) que nadie capturaba: el trabajo se
    quedaba en PROCESSING y se releía, y fallaba, en cada ciclo.
    """

    segment_format = "note_segment" in raw
    allowed = _SEGMENT_ALLOWED if segment_format else _LEGACY_ALLOWED
    required = ({"note_segment", "source_segments", "claim_type", "volatility", "entities"} if segment_format
                else {"statement", "claim_type", "volatility", "quote", "entities"})
    if not required.issubset(raw) or set(raw) - allowed:
        raise SemanticContractError(f"Claim {index} no cumple el contrato")
    if segment_format:
        links = raw["source_segments"]
        if not isinstance(raw["note_segment"], str) or not isinstance(links, list) \
                or any(not isinstance(item, str) for item in links):
            raise SemanticContractError(f"Claim {index} tiene identificadores de segmento inválidos")
    else:
        if not isinstance(raw["quote"], str) or not isinstance(raw["statement"], str) \
                or not raw["statement"].strip():
            raise SemanticContractError(f"Claim {index} tiene texto o entidades inválidos")
    claim_type, entities, volatility = raw["claim_type"], raw["entities"], raw["volatility"]
    if not isinstance(claim_type, str) or not claim_type.strip() or not isinstance(entities, list) \
            or any(not isinstance(item, str) for item in entities):
        raise SemanticContractError(f"Claim {index} tiene texto o entidades inválidos")
    if not isinstance(volatility, str) or volatility not in {"LOW", "MEDIUM", "HIGH"}:
        raise SemanticContractError(f"Claim {index} tiene volatilidad inválida")
    manual_lock = raw.get("manual_lock", False)
    if not isinstance(manual_lock, bool):
        raise SemanticContractError(f"Claim {index} tiene manual_lock inválido")
    for field in ("observed_at", "source_date"):
        value = raw.get(field)
        if value is not None and not (isinstance(value, str) and AnalisisMixin._valid_date(value)):
            raise SemanticContractError(f"Claim {index} tiene {field} inválido")
    return {
        "claim_type": claim_type.strip(), "volatility": volatility, "entities": tuple(entities),
        "observed_at": raw.get("observed_at"), "source_date": raw.get("source_date"),
        "manual_lock": manual_lock,
    }


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
    def _parse_extraction(payload: Mapping[str, Any], document: str, source: str = "") -> list[ExtractedClaim]:
        return AnalisisMixin._parse_extraction_report(payload, document, source).claims

    @staticmethod
    def _parse_extraction_report(
        payload: Mapping[str, Any], document: str, source: str = "",
    ) -> ExtractionReport:
        """Valida la respuesta entera antes de crear nada y gradúa el respaldo de cada claim.

        Estructura y tipos se comprueban primero y de forma completa: un valor
        inesperado (una lista donde va un texto) es un fallo de contrato del
        trabajo, no un `TypeError` que deja el análisis en PROCESSING y bloquea
        la cola (auditoría H04). Una frase de la nota que no existe invalida la
        respuesta entera, igual que antes una cita inventada.
        """

        if not isinstance(payload, Mapping) or set(payload) != {"claims"} \
                or not isinstance(payload.get("claims"), list):
            raise SemanticContractError("La extracción debe contener únicamente claims[]")
        body_start = AnalisisMixin._body_start(document)
        historical_start = history_boundary(document)
        notes = {segment.segment_id: segment for segment in note_segments(
            document, body_start=body_start, body_end=historical_start,
        )}
        sources = source_segments(source) if source else []
        result: list[ExtractedClaim] = []
        ignored_links = 0
        unknown_segments = 0
        for index, raw in enumerate(payload["claims"]):
            if not isinstance(raw, Mapping):
                raise SemanticContractError(f"Claim {index} no cumple el contrato")
            fields = _validated_fields(raw, index)
            if "note_segment" in raw:
                segment = notes.get(raw["note_segment"])
                if segment is None:
                    # Un identificador inexistente no aporta texto que colar: se
                    # descarta y se cuenta (queda en la cronología). Antes uno
                    # solo —N90 en una nota de 89 frases, contra el Broker real—
                    # tiraba las otras 24 afirmaciones válidas.
                    unknown_segments += 1
                    continue
                start, end = segment.start, segment.end
                known = {item.segment_id for item in sources}
                hinted = tuple(item for item in raw["source_segments"] if item in known)
                ignored_links += len(raw["source_segments"]) - len(hinted)
            else:
                span = _offered_span(document, raw, body_start=body_start, index=index)
                if span is None:
                    span = locate_quote(document, raw["quote"], body_start=body_start)
                # Sin cita localizable no hay evidencia: así el modelo no cuela
                # conocimiento externo ni citas que el documento no contiene.
                if span is None:
                    raise SemanticContractError(f"Claim {index} no está respaldado por su span local")
                start, end = span
                if " ".join(raw["statement"].split()) != " ".join(raw["quote"].split()):
                    raise SemanticContractError(
                        f'Claim {index}: statement debe conservar la cita, sin añadir inferencias'
                    )
                hinted = ()
            if historical_start is not None:
                if start >= historical_start:
                    continue  # El contenido histórico no se reintroduce como conocimiento vigente.
                if end > historical_start:
                    raise SemanticContractError('El span mezcla conocimiento vigente e histórico')
            # La evidencia guardada es el texto del documento, no la versión del
            # modelo: parches, deriva y procedencia exigen que
            # `document[span_start:span_end]` sea exactamente la cita.
            evidence = document[start:end]
            support, matches = (
                find_support(evidence, source, sources, hinted=hinted) if sources else ("SUMMARY_ONLY", [])
            )
            result.append(ExtractedClaim(
                statement=evidence, claim_type=fields["claim_type"], volatility=fields["volatility"],
                span_start=start, span_end=end, quote=evidence, entities=fields["entities"],
                observed_at=fields["observed_at"], source_date=fields["source_date"],
                manual_lock=fields["manual_lock"], source_support=support,
                source_evidence=tuple(
                    SourceEvidence(match.start, match.end, match.quote, match.method, match.score)
                    for match in matches
                ),
            ))
        if unknown_segments and unknown_segments == len(payload["claims"]):
            raise SemanticContractError("Ninguna afirmación señala una frase existente de la nota")
        return ExtractionReport(claims=result, ignored_source_links=ignored_links,
                                unknown_note_segments=unknown_segments)

    @staticmethod
    def _parse_comparison(payload: Mapping[str, Any]) -> ComparisonDecision:
        required = {"relation", "confidence", "impact", "rationale", "replacement_text"}
        if not isinstance(payload, Mapping) or set(payload) != required:
            raise SemanticContractError("La comparación no cumple el contrato")
        relation = payload["relation"]
        confidence = payload["confidence"]
        impact = payload["impact"]
        rationale = payload["rationale"]
        if not isinstance(relation, str) or relation not in {
            "SUPPORTS", "EXTENDS", "CONTRADICTS", "SUPERSEDES", "UNRELATED", "UNCERTAIN",
        }:
            raise SemanticContractError("Relación inválida")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise SemanticContractError("Confianza inválida")
        if not isinstance(impact, str) or impact not in {"LOW", "MEDIUM", "HIGH"} \
                or not isinstance(rationale, str) or not rationale.strip():
            raise SemanticContractError("Impacto o rationale inválido")
        replacement = payload["replacement_text"]
        if replacement is not None and not isinstance(replacement, str):
            raise SemanticContractError("replacement_text inválido")
        if relation in {"SUPPORTS", "UNRELATED", "UNCERTAIN"}:
            # Estas relaciones no modifican nada: si el modelo rellena el texto
            # (o escribe "null" entre comillas, visto en real), se ignora en vez
            # de perder la clasificación. No se genera ningún parche.
            replacement = None
        return ComparisonDecision(
            cast(Any, relation), float(confidence), cast(Impact, impact), rationale.strip(), replacement,
        )

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
