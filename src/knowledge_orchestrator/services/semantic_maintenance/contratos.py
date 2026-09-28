"""El contrato con el modelo: error, esquemas de extracción y de comparación.

Los esquemas son estrictos a propósito (`additionalProperties: false`): un
modelo que devuelve un campo de más está devolviendo algo que nadie pidió, y
aquí eso se rechaza en vez de ignorarse.
"""
from __future__ import annotations

from typing import Any


class SemanticContractError(ValueError):
    pass


#: Afirmaciones que se piden por nota: las más informativas.
MAX_CLAIMS_PER_NOTE = 25


#: Contrato de extracción por segmentos (0.4.0). El modelo no escribe ni copia
#: texto: señala qué frase de la nota (N#) es una afirmación y qué tramos de la
#: fuente original (S#) la respaldan. El texto lo pone la aplicación.
EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["claims"],
    "properties": {
        "claims": {
            "type": "array",
            # Acotado a propósito: contra el Broker real, sin límite, el modelo
            # enumeraba las 121 frases de una nota, agotaba los 6000 tokens y
            # devolvía un JSON cortado. Mejor 25 buenas que ninguna.
            "maxItems": MAX_CLAIMS_PER_NOTE,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["note_segment", "source_segments", "claim_type", "volatility", "entities"],
                "properties": {
                    "note_segment": {"type": "string"},
                    "source_segments": {"type": "array", "maxItems": 3, "items": {"type": "string"}},
                    "claim_type": {"type": "string"},
                    "volatility": {"enum": ["LOW", "MEDIUM", "HIGH"]},
                    "entities": {"type": "array", "maxItems": 5, "items": {"type": "string"}},
                    "observed_at": {"type": ["string", "null"]},
                    "source_date": {"type": ["string", "null"]},
                    "manual_lock": {"type": "boolean"},
                },
            },
        }
    },
}


#: Contrato anterior, por cita literal. Se sigue aceptando al leer (respuestas
#: ya recibidas, integraciones y pruebas), con la misma exigencia de siempre:
#: una cita que no esté en la nota invalida la respuesta entera.
LEGACY_EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["claims"],
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                # Sin `span_start`/`span_end`: eran obligatorios y ningún modelo
                # los acertaba —contar caracteres no es algo que un LLM pueda
                # hacer—, así que los calcula la aplicación a partir de la cita.
                # Se siguen aceptando, y se respetan cuando resultan correctos.
                "required": ["statement", "claim_type", "volatility", "quote", "entities"],
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
