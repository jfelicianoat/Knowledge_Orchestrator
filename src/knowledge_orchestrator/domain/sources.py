from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .models import CaptureDocument, SourceOrigin


def infer_source_origin(document: CaptureDocument) -> SourceOrigin:
    if document.source_type == "youtube" and document.metadata.get("plugin_version"):
        return SourceOrigin.PLUGIN_CAPTURE
    if document.source_type == "obsidian_note":
        return SourceOrigin.OBSIDIAN_NOTE
    return SourceOrigin.USER_FILE


AUTONOMOUS_SOURCE_FEATURES = frozenset({
    "rss",
    "watched_documentation",
    "automatic_api_connector",
    "autonomous_web_search",
})

PROHIBITED_SOURCE_TYPES = frozenset({
    "rss",
    "api",
    "web_search",
    "web_crawl",
    "autonomous_web_search",
    "api_connector",
    "automatic_api_connector",
    "watched_documentation",
    "monitored_documentation",
    "documentation_watch",
})


#: Clave de la captura que pide publicar el texto tal cual, sin resumirlo con el Broker.
OWN_NOTES_KEY = "own_notes"


def is_own_note(metadata: Mapping[str, Any] | str | None) -> bool:
    """¿Es un apunte propio? Acepta el metadata ya leído o su JSON guardado en `captures`."""

    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except ValueError:
            return False
    return isinstance(metadata, Mapping) and metadata.get(OWN_NOTES_KEY) is True


def is_prohibited_source_type(source_type: str) -> bool:
    return source_type.strip().casefold().replace("-", "_") in PROHIBITED_SOURCE_TYPES


def autonomous_sources_enabled() -> bool:
    """Conectores controlados disponibles; las capturas crudas no pueden suplantarlos."""
    return True
