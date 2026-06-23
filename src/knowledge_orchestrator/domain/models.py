from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


class CaptureStatus(str, Enum):
    STAGED = "STAGED"
    PENDING = "PENDING"
    SUBMITTING = "SUBMITTING"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class CaptureDocument:
    metadata: Mapping[str, Any]
    transcript_content: str
    raw_markdown: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def capture_id(self) -> str:
        return str(self.metadata["capture_id"])

    @property
    def contract_version(self) -> str:
        return str(self.metadata["contract_version"])

    @property
    def source_type(self) -> str:
        return str(self.metadata["source_type"])

    @property
    def title(self) -> str:
        return str(self.metadata["title"])


@dataclass(frozen=True, slots=True)
class CaptureRecord:
    capture_id: str
    contract_version: str
    source_type: str
    title: str
    status: CaptureStatus
    source_path: Path | None
    staging_path: Path | None
    processing_path: Path | None
    sha256: str
    original_filename: str
    metadata_json: str
    transcript_content: str
    last_error_code: str | None = None
    last_error_message: str | None = None


@dataclass(frozen=True, slots=True)
class IngestionResult:
    accepted: bool
    capture_id: str | None
    status: CaptureStatus | None
    error_code: str | None = None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class ApplicationEvent:
    event_type: str
    capture_id: str | None
    message: str
    details: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))
