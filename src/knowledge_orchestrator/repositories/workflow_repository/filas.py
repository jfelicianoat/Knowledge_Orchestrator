"""Traducción de filas SQLite a los registros del dominio.

Está aparte porque lo usa casi todo el repositorio y no depende de nada
más: es la frontera entre la forma de la tabla y la del dominio.
"""
from __future__ import annotations

import sqlite3

from knowledge_orchestrator.domain.broker_models import (
    BrokerTaskRecord,
    StepKind,
    TaskStatus,
    WorkflowRecord,
    WorkflowStatus,
)


def _task(row: sqlite3.Row) -> BrokerTaskRecord:
    return BrokerTaskRecord(
        task_id=row["task_id"],
        workflow_id=row["workflow_id"],
        capture_id=row["capture_id"],
        step_id=row["step_id"],
        step_kind=StepKind(row["step_kind"]),
        sequence_index=row["sequence_index"],
        status=TaskStatus(row["status"]),
        idempotency_key=row["idempotency_key"],
        request_json=row["request_json"],
        input_text=row["input_text"],
        attempt=row["attempt"],
        next_retry_at=row["next_retry_at"],
        status_url=row["status_url"],
        cancel_url=row["cancel_url"],
        result_json=row["result_json"],
        error_code=row["error_code"],
        error_message=row["error_message"],
        error_retryable=bool(row["error_retryable"]) if row["error_retryable"] is not None else None,
        broker_task_id=row["broker_task_id"],
        execution_strategy=row["execution_strategy"],
        execution_preset=row["execution_preset"],
        selection_mode=row["selection_mode"],
        progress_json=row["progress_json"],
        strategy_fallback_allowed=bool(row["strategy_fallback_allowed"]),
        replacement_for_task_id=row["replacement_for_task_id"],
    )


def _workflow(row: sqlite3.Row) -> WorkflowRecord:
    return WorkflowRecord(
        workflow_id=row["workflow_id"],
        capture_id=row["capture_id"],
        revision=row["revision"],
        profile_id=row["profile_id"],
        profile_revision=row["profile_revision"],
        status=WorkflowStatus(row["status"]),
        strategy=row["strategy"],
        total_steps=row["total_steps"],
        completed_steps=row["completed_steps"],
        final_result=row["final_result"],
        error_code=row["error_code"],
        error_message=row["error_message"],
    )
