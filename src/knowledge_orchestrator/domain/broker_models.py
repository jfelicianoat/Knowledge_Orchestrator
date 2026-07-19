from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any


class WorkflowStatus(str, Enum):
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"


class TaskStatus(str, Enum):
    READY = "READY"
    BLOCKED = "BLOCKED"
    SUBMITTING = "SUBMITTING"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"


class StepKind(str, Enum):
    SINGLE = "SINGLE"
    CHUNK = "CHUNK"
    SYNTHESIS = "SYNTHESIS"
    EMBEDDING = "EMBEDDING"


@dataclass(frozen=True, slots=True)
class PlannedTask:
    task_id: str
    workflow_id: str
    capture_id: str
    step_id: str
    step_kind: StepKind
    sequence_index: int
    idempotency_key: str
    request: Mapping[str, Any]
    input_text: str
    strategy_fallback_allowed: bool = False
    replacement_for_task_id: str | None = None


@dataclass(frozen=True, slots=True)
class BrokerTaskRecord:
    task_id: str
    workflow_id: str
    capture_id: str
    step_id: str
    step_kind: StepKind
    sequence_index: int
    status: TaskStatus
    idempotency_key: str
    request_json: str
    input_text: str
    attempt: int
    next_retry_at: str | None
    status_url: str | None
    result_json: str | None
    error_code: str | None
    error_message: str | None
    error_retryable: bool | None
    broker_task_id: str | None = None
    execution_strategy: str = "single"
    execution_preset: str = "fast"
    selection_mode: str = "auto"
    progress_json: str = "{}"
    strategy_fallback_allowed: bool = False
    replacement_for_task_id: str | None = None


@dataclass(frozen=True, slots=True)
class WorkflowRecord:
    workflow_id: str
    capture_id: str
    revision: int
    profile_id: int
    profile_revision: int
    status: WorkflowStatus
    strategy: str
    total_steps: int
    completed_steps: int
    final_result: str | None
    error_code: str | None
    error_message: str | None
