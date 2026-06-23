from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Mapping

UNRESOLVED_PLACEHOLDER = re.compile(
    r"\{(?:title|channel|transcript|published_date|captured_at|source_type|source_url|"
    r"chunk|chunk_index|chunk_count|partial_results)\}"
)
TASK_ID = re.compile(r"^[A-Za-z0-9._:-]{1,240}$")
TASK_STATUSES = {
    "queued", "processing", "success", "error", "cancel_requested", "cancelled"
}


@dataclass(frozen=True, slots=True)
class BrokerContractIssue:
    boundary: str
    field: str
    reason: str
    contract_version: str | None = "1.0"
    code: str = "CONTRACT_VALIDATION_FAILED"


class BrokerContractError(ValueError):
    def __init__(self, issue: BrokerContractIssue):
        super().__init__(f"{issue.boundary}: {issue.field}: {issue.reason}")
        self.issue = issue


def _fail(boundary: str, field: str, reason: str, version: str | None = "1.0") -> None:
    raise BrokerContractError(BrokerContractIssue(boundary, field, reason, version))


def _mapping(value: Any, boundary: str, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(boundary, field, "debe ser un objeto")
    return value


def _string(value: Any, boundary: str, field: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value.strip()):
        _fail(boundary, field, "debe ser string no vacío")
    return value


def validate_create_task_request(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    boundary = "orchestrator_to_broker"
    if payload.get("contract_version") != "1.0":
        _fail(boundary, "contract_version", "debe ser 1.0", str(payload.get("contract_version")))
    task_id = _string(payload.get("task_id"), boundary, "task_id")
    if not TASK_ID.fullmatch(task_id):
        _fail(boundary, "task_id", "formato o longitud no permitidos")
    _string(payload.get("idempotency_key"), boundary, "idempotency_key")
    routing = _mapping(payload.get("routing"), boundary, "routing")
    _string(routing.get("preferred_model"), boundary, "routing.preferred_model")
    if not isinstance(routing.get("fallback_allowed"), bool):
        _fail(boundary, "routing.fallback_allowed", "debe ser boolean")
    if routing.get("quality_priority") not in {"low", "balanced", "high"}:
        _fail(boundary, "routing.quality_priority", "valor no permitido")
    max_cost = routing.get("max_cost_usd")
    if not isinstance(max_cost, (int, float)) or isinstance(max_cost, bool) or max_cost < 0:
        _fail(boundary, "routing.max_cost_usd", "debe ser número no negativo")

    inference = _mapping(payload.get("inference"), boundary, "inference")
    kind = inference.get("kind")
    if kind == "chat":
        messages = inference.get("messages")
        if not isinstance(messages, list) or len(messages) < 2:
            _fail(boundary, "inference.messages", "debe contener al menos system y user")
        for index, message in enumerate(messages):
            item = _mapping(message, boundary, f"inference.messages[{index}]")
            if item.get("role") not in {"system", "user", "assistant"}:
                _fail(boundary, f"inference.messages[{index}].role", "rol no permitido")
            content = _string(item.get("content"), boundary, f"inference.messages[{index}].content")
            if UNRESOLVED_PLACEHOLDER.search(content):
                _fail(boundary, f"inference.messages[{index}].content", "contiene placeholders sin resolver")
        temperature = inference.get("temperature")
        if not isinstance(temperature, (int, float)) or isinstance(temperature, bool) or not 0 <= temperature <= 2:
            _fail(boundary, "inference.temperature", "debe estar entre 0 y 2")
        tokens = inference.get("max_output_tokens")
        if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens < 1:
            _fail(boundary, "inference.max_output_tokens", "debe ser integer positivo")
        if inference.get("response_format") not in {"text", "json"}:
            _fail(boundary, "inference.response_format", "debe ser text o json")
    elif kind == "embedding":
        _string(inference.get("input"), boundary, "inference.input")
        _string(inference.get("model"), boundary, "inference.model")
    else:
        _fail(boundary, "inference.kind", "debe ser chat o embedding")

    context = _mapping(payload.get("client_context"), boundary, "client_context")
    _string(context.get("workflow_id"), boundary, "client_context.workflow_id")
    _string(context.get("step_id"), boundary, "client_context.step_id")
    return payload


def validate_accepted_response(payload: Mapping[str, Any], expected_task_id: str) -> Mapping[str, Any]:
    boundary = "broker_to_orchestrator"
    if payload.get("task_id") != expected_task_id:
        _fail(boundary, "task_id", "no coincide con la tarea enviada")
    if payload.get("status") != "queued":
        _fail(boundary, "status", "la aceptación debe devolver queued")
    for field in ("status_url", "cancel_url"):
        value = _string(payload.get(field), boundary, field)
        if not value.startswith("/"):
            _fail(boundary, field, "debe ser una ruta relativa absoluta")
    return payload


def validate_task_status_response(
    payload: Mapping[str, Any],
    expected_task_id: str,
    *,
    expected_kind: str = "chat",
) -> Mapping[str, Any]:
    boundary = "broker_to_orchestrator"
    if payload.get("task_id") != expected_task_id:
        _fail(boundary, "task_id", "no coincide con la tarea consultada")
    status = payload.get("status")
    if status not in TASK_STATUSES:
        _fail(boundary, "status", "estado no permitido")
    if status == "success":
        result = _mapping(payload.get("result"), boundary, "result")
        if expected_kind == "chat":
            _string(result.get("assistant_content"), boundary, "result.assistant_content")
        else:
            embedding = result.get("embedding")
            if not isinstance(embedding, list) or not embedding:
                _fail(boundary, "result.embedding", "debe ser un vector no vacío")
            if any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(float(value))
                for value in embedding
            ):
                _fail(boundary, "result.embedding", "contiene valores no numéricos o no finitos")
            if result.get("dimensions") != len(embedding):
                _fail(boundary, "result.dimensions", "no coincide con el vector")
        if payload.get("error") is not None:
            _fail(boundary, "error", "debe ser null en success")
    elif status == "error":
        error = _mapping(payload.get("error"), boundary, "error")
        _string(error.get("code"), boundary, "error.code")
        _string(error.get("message"), boundary, "error.message")
        if not isinstance(error.get("retryable"), bool):
            _fail(boundary, "error.retryable", "debe ser boolean")
    elif status == "cancelled":
        if payload.get("result") is not None:
            _fail(boundary, "result", "debe ser null en cancelled")
    return payload


def validate_models_response(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    boundary = "broker_to_orchestrator"
    models = payload.get("models")
    if not isinstance(models, list):
        combined: list[Any] = []
        for field in ("local_models", "external_models"):
            value = payload.get(field, [])
            if not isinstance(value, list):
                _fail(boundary, field, "debe ser una lista")
            combined.extend(value)
        models = combined
    validated: list[Mapping[str, Any]] = []
    for index, model in enumerate(models):
        item = _mapping(model, boundary, f"models[{index}]")
        _string(item.get("name"), boundary, f"models[{index}].name")
        status = item.get("status")
        if status not in {"available", "loaded", "online", "offline", "unavailable"}:
            _fail(boundary, f"models[{index}].status", "estado no permitido")
        validated.append(item)
    return validated
