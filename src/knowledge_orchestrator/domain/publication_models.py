from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PublishableWorkflow:
    workflow_id: str
    capture_id: str
    revision: int
    final_result: str
    profile_id: int
    topic_id: int
    processed_at: str


@dataclass(frozen=True, slots=True)
class NoteRecord:
    note_id: int
    capture_id: str
    workflow_id: str
    revision: int
    status: str
    vault_path: Path
    temp_path: Path | None
    content_hash: str
    rejected_path: Path | None
    source_archive_path: Path


@dataclass(frozen=True, slots=True)
class ReprocessIntent:
    intent_id: int
    capture_id: str
    source_note_id: int
    revision: int
    source_path: Path
    target_path: Path
    status: str
