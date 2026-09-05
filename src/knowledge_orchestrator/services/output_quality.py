"""Comprobaciones conservadoras antes de aceptar apuntes generados."""
from __future__ import annotations

import re

_MISSING_EXECUTION = (
    "what would you like me to do",
    "what would you like me to",
    "there is no specific question",
    "there's no specific question",
    "no specific request",
    "just let me know what you're after",
    "qué te gustaría hacer ahora",
    "no incluyes una pregunta concreta",
    "dime cuál de estos",
)
_SPANISH_WORDS = {"el", "la", "los", "las", "que", "de", "para", "con", "una", "como", "en", "se", "por"}
_ENGLISH_WORDS = {"the", "and", "that", "for", "with", "this", "from", "are", "to", "of", "in", "you"}


def study_notes_quality_error(text: str, *, final: bool) -> str | None:
    """Devuelve un código solo para defectos inequívocos, evitando falsos positivos."""

    normalized = text.strip()
    lowered = normalized.casefold()
    if any(marker in lowered for marker in _MISSING_EXECUTION):
        return "MISSING_EXECUTION"
    if not final:
        return None
    words = re.findall(r"[a-záéíóúüñ]+", lowered)
    spanish = sum(word in _SPANISH_WORDS for word in words)
    english = sum(word in _ENGLISH_WORDS for word in words)
    if len(words) >= 80 and english >= 12 and english > spanish * 3 / 2:
        return "WRONG_LANGUAGE"
    last_line = next((line.strip() for line in reversed(normalized.splitlines()) if line.strip()), "")
    if (len(normalized) >= 500 and re.fullmatch(r"#{1,6}\s+.+", last_line)) or normalized.count("```") % 2:
        return "TRUNCATED_OUTPUT"
    return None


def study_notes_quality_message(code: str) -> str:
    messages = {
        "MISSING_EXECUTION": "El modelo pidió instrucciones en vez de crear los apuntes.",
        "WRONG_LANGUAGE": "El modelo respondió principalmente en inglés; los apuntes deben estar en español.",
        "TRUNCATED_OUTPUT": "La respuesta parece haberse cortado antes de terminar.",
    }
    return messages.get(code, "La respuesta no cumple la calidad mínima para publicarse.")
