"""El contrato con el modelo: error, esquemas de extracción y de comparación.

Los esquemas son estrictos a propósito (`additionalProperties: false`): un
modelo que devuelve un campo de más está devolviendo algo que nadie pidió, y
aquí eso se rechaza en vez de ignorarse.
"""
from __future__ import annotations

from typing import Any


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
