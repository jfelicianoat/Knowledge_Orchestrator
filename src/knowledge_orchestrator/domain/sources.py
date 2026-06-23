from __future__ import annotations

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


def is_prohibited_source_type(source_type: str) -> bool:
    return source_type.strip().casefold().replace("-", "_") in PROHIBITED_SOURCE_TYPES


def autonomous_sources_enabled() -> bool:
    """Contrato explícito del MVP: no existe ningún productor autónomo de fuentes."""
    return False
