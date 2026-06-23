from __future__ import annotations

from pathlib import Path

from knowledge_orchestrator.config import PipelinePaths
from knowledge_orchestrator.repositories.capture_repository import CaptureRepository
from knowledge_orchestrator.repositories.database import Database
from knowledge_orchestrator.services.file_stability import FileStabilityChecker
from knowledge_orchestrator.services.ingestion import IngestionService


def valid_markdown(
    *,
    capture_id: str = "yt_20260622_120000_dQw4w9WgXcQ",
    has_transcript: bool = True,
) -> bytes:
    transcript_source = '"manual"' if has_transcript else "null"
    transcript_language = '"es"' if has_transcript else "null"
    transcript = "[00:00:00] Contenido de prueba." if has_transcript else ""
    return f'''---
contract_version: "1.0"
capture_id: "{capture_id}"
source_type: "youtube"
source_url: "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
video_id: "dQw4w9WgXcQ"
title: "Vídeo de prueba"
channel: "Canal de prueba"
channel_url: "https://www.youtube.com/@canal"
duration_seconds: 120
published_date: "2026-06-20"
captured_at: "2026-06-22T12:00:00Z"
transcript_language: {transcript_language}
has_transcript: {str(has_transcript).lower()}
transcript_source: {transcript_source}
extraction_method: "schema_jsonld"
plugin_version: "0.1.0"
status: "pending"
---

# Vídeo de prueba

## Transcripción

{transcript}
'''.encode("utf-8")


def generic_markdown(
    *,
    capture_id: str = "document_20260623_python",
    title: str = "Curso práctico de Python",
    source_type: str = "document",
) -> bytes:
    return f'''---
contract_version: "1.0"
capture_id: "{capture_id}"
source_type: "{source_type}"
title: "{title}"
captured_at: "2026-06-23T10:00:00Z"
has_transcript: true
status: "pending"
tags: [programación, python]
---

# {title}

## Transcripción

Contenido aportado manualmente por el usuario.
'''.encode("utf-8")


def runtime(root: Path, *, checkpoint=None) -> tuple[PipelinePaths, Database, CaptureRepository, IngestionService]:
    paths = PipelinePaths.under(root)
    paths.ensure_directories()
    database = Database(paths.database)
    database.initialize()
    repository = CaptureRepository(database)
    checker = FileStabilityChecker(interval_seconds=0, sleep=lambda _seconds: None)
    ingestion = IngestionService(paths, repository, stability_checker=checker, checkpoint=checkpoint)
    return paths, database, repository, ingestion
