from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, NoReturn

UNRESOLVED_PLACEHOLDER = re.compile(
    r"\{(?:title|channel|transcript|published_date|captured_at|source_type|source_url|"
    r"chunk|chunk_index|chunk_count|partial_results)\}"
)
IDENTIFIER = re.compile(r"^[A-Za-z0-9._:-]{1,240}$")
# Estados publicados por el contrato 2.7. Los intermedios son informativos y
# aditivos: el cliente debe aceptar otros nuevos y seguir sondeando.
BROKER_STATUSES = {
    "queued", "waiting_for_memory", "routing", "planning", "resource_planning", "chunking", "generating",
    "proposing", "evaluating", "debating", "synthesizing", "verifying",
    # Carril de ingesta de ficheros.
    "converting",
    # Estrategia agent con tool-calls del cliente pendientes (no terminal).
    "waiting_for_tools",
    "completed", "failed", "cancelled",
}
# single/mixture_of_agents: clásicas. agent: bucle ReAct con skills del Broker.
# auto: el meta-router del Broker elige la estrategia; la respuesta conserva
# "auto" en execution_strategy y la resolución queda en el evento strategy.routed.
BROKER_STRATEGIES = {"single", "mixture_of_agents", "agent", "auto"}
BROKER_PRESETS = {"fast", "slow", "standard", "verified", "high_stakes"}


@dataclass(frozen=True, slots=True)
class BrokerContractIssue:
    boundary: str
    field: str
    reason: str
    contract_version: str | None = "2.7"
    code: str = "CONTRACT_VALIDATION_FAILED"


class BrokerContractError(ValueError):
    def __init__(self, issue: BrokerContractIssue):
        super().__init__(f"{issue.boundary}: {issue.field}: {issue.reason}")
        self.issue = issue


def _fail(boundary: str, field: str, reason: str) -> NoReturn:
    raise BrokerContractError(BrokerContractIssue(boundary, field, reason))


def _mapping(value: Any, boundary: str, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(boundary, field, "debe ser un objeto")
    return value


def _string(value: Any, boundary: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(boundary, field, "debe ser string no vacío")
    return value


def validate_create_task_request(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    boundary = "orchestrator_to_broker_v2"
    key = _string(payload.get("idempotency_key"), boundary, "idempotency_key")
    if not IDENTIFIER.fullmatch(key):
        _fail(boundary, "idempotency_key", "formato o longitud no permitido")
    request_id = _string(payload.get("request_id"), boundary, "request_id")
    if len(request_id) > 240:
        _fail(boundary, "request_id", "supera 240 caracteres")

    content = _mapping(payload.get("content"), boundary, "content")
    prompt = _string(content.get("prompt"), boundary, "content.prompt")
    if UNRESOLVED_PLACEHOLDER.search(prompt):
        _fail(boundary, "content.prompt", "contiene placeholders sin resolver")
    if not isinstance(content.get("attachments", []), list):
        _fail(boundary, "content.attachments", "debe ser una lista")
    _mapping(content.get("metadata", {}), boundary, "content.metadata")

    output = _mapping(payload.get("output"), boundary, "output")
    if output.get("format") not in {"markdown", "text", "json"}:
        _fail(boundary, "output.format", "formato no permitido")
    _string(output.get("language"), boundary, "output.language")
    if output.get("format") == "json" and not isinstance(output.get("json_schema"), Mapping):
        _fail(boundary, "output.json_schema", "es obligatorio para JSON")

    generation = _mapping(payload.get("generation"), boundary, "generation")
    temperature = generation.get("temperature")
    if not isinstance(temperature, (int, float)) or isinstance(temperature, bool) or not 0 <= temperature <= 2:
        _fail(boundary, "generation.temperature", "debe estar entre 0 y 2")
    tokens = generation.get("max_output_tokens")
    if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens < 1:
        _fail(boundary, "generation.max_output_tokens", "debe ser integer positivo")

    requirements = _mapping(payload.get("model_requirements"), boundary, "model_requirements")
    if requirements.get("preferred_model") is not None:
        preferred_model = _string(
            requirements.get("preferred_model"), boundary, "model_requirements.preferred_model"
        )
        if len(preferred_model) > 128:
            _fail(boundary, "model_requirements.preferred_model", "supera 128 caracteres")
    if not isinstance(requirements.get("fallback_allowed"), bool):
        _fail(boundary, "model_requirements.fallback_allowed", "debe ser boolean")
    cloud_allowed = requirements.get("cloud_allowed")
    if cloud_allowed is not None and not isinstance(cloud_allowed, bool):
        _fail(boundary, "model_requirements.cloud_allowed", "debe ser boolean o null")
    providers = requirements.get("allowed_providers")
    if providers is not None and (
        not isinstance(providers, list) or not providers or any(
            not isinstance(item, str) or not item for item in providers
        )
    ):
        _fail(boundary, "model_requirements.allowed_providers", "debe ser una lista no vacía o null")
    cost = requirements.get("max_cost_usd")
    if cost is not None and (not isinstance(cost, (int, float)) or isinstance(cost, bool) or cost < 0):
        _fail(boundary, "model_requirements.max_cost_usd", "debe ser número no negativo o null")

    execution = _mapping(payload.get("execution"), boundary, "execution")
    if execution.get("strategy") not in BROKER_STRATEGIES:
        _fail(boundary, "execution.strategy", "estrategia no permitida")
    if execution.get("preset") not in BROKER_PRESETS:
        _fail(boundary, "execution.preset", "preset no permitido")
    if execution.get("scheduling") not in {"adaptive", "parallel", "waves", "sequential"}:
        _fail(boundary, "execution.scheduling", "scheduling no permitido")
    selection = _mapping(execution.get("selection"), boundary, "execution.selection")
    if selection.get("mode") not in {"auto", "manual", "hybrid"}:
        _fail(boundary, "execution.selection.mode", "modo no permitido")
    limits = {
        "max_proposers": (1, 5),
        "max_judges": (0, 2),
        "max_rounds": (1, 2),
    }
    for field, (minimum, maximum) in limits.items():
        value = execution.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
            _fail(boundary, f"execution.{field}", f"debe estar entre {minimum} y {maximum}")
    timeout = execution.get("timeout_seconds")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 1:
        _fail(boundary, "execution.timeout_seconds", "debe ser integer positivo")
    if not isinstance(execution.get("early_stop"), bool):
        _fail(boundary, "execution.early_stop", "debe ser boolean")
    proposer_count = selection.get("proposer_count")
    if not isinstance(proposer_count, int) or isinstance(proposer_count, bool) or not 1 <= proposer_count <= 5:
        _fail(boundary, "execution.selection.proposer_count", "debe estar entre 1 y 5")
    if execution.get("long_context", "fail") not in {"fail", "map_reduce"}:
        _fail(boundary, "execution.long_context", "política no permitida")
    if execution.get("long_context") == "map_reduce" and execution.get("strategy") not in {"single", "auto"}:
        _fail(boundary, "execution.long_context", "map_reduce solo admite single o auto")

    risk = _mapping(payload.get("risk"), boundary, "risk")
    if risk.get("data_classification") not in {"public", "internal", "confidential", "local_only"}:
        _fail(boundary, "risk.data_classification", "clasificación no permitida")
    if not isinstance(risk.get("human_review_required"), bool):
        _fail(boundary, "risk.human_review_required", "debe ser boolean")
    if not isinstance(payload.get("priority"), int) or not 0 <= payload["priority"] <= 1000:
        _fail(boundary, "priority", "debe estar entre 0 y 1000")
    if payload.get("prompt_compression") not in {None, "off", "light", "medium", "aggressive"}:
        _fail(boundary, "prompt_compression", "política no permitida")
    cloudish = {"deepseek", "ollama_cloud", "openai", "anthropic", "google"}
    normalized_providers = {provider.lower() for provider in providers or []}
    if cloud_allowed is False and normalized_providers & cloudish:
        _fail(boundary, "model_requirements.allowed_providers", "incluye cloud con cloud_allowed=false")
    if risk["data_classification"] in {"confidential", "local_only"}:
        if cloud_allowed is True:
            _fail(boundary, "risk.data_classification", "la clasificación no permite cloud")
        if normalized_providers & cloudish:
            _fail(boundary, "model_requirements.allowed_providers", "incluye cloud para datos restringidos")
    return payload


def validate_accepted_response(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    boundary = "broker_to_orchestrator_v2"
    _string(payload.get("task_id"), boundary, "task_id")
    _string(payload.get("status"), boundary, "status")
    if payload.get("execution_strategy") not in BROKER_STRATEGIES:
        _fail(boundary, "execution_strategy", "estrategia no permitida")
    if payload.get("execution_preset") not in BROKER_PRESETS:
        _fail(boundary, "execution_preset", "preset no permitido")
    if payload.get("selection_mode") not in {"auto", "manual", "hybrid"}:
        _fail(boundary, "selection_mode", "modo no permitido")
    for field in ("status_url", "cancel_url"):
        if not _string(payload.get(field), boundary, field).startswith("/"):
            _fail(boundary, field, "debe ser una ruta relativa absoluta")
    return payload


def validate_task_status_response(payload: Mapping[str, Any], expected_task_id: str) -> Mapping[str, Any]:
    boundary = "broker_to_orchestrator_v2"
    if payload.get("task_id") != expected_task_id:
        _fail(boundary, "task_id", "no coincide con la tarea del Broker")
    # El Broker garantiza los estados terminales, pero puede incorporar fases
    # intermedias sin subir la versión del contrato. Cualquier string no vacío
    # que no sea terminal se conserva como estado de trabajo.
    status = _string(payload.get("status"), boundary, "status")
    _string(payload.get("created_at"), boundary, "created_at")
    _string(payload.get("updated_at"), boundary, "updated_at")
    progress = _mapping(payload.get("progress", {}), boundary, "progress")
    _string(progress.get("phase"), boundary, "progress.phase")
    kind = payload.get("kind", "inference")
    if kind not in {"inference", "ingestion"}:
        _fail(boundary, "kind", "tipo de tarea no permitido")
    strategy = payload.get("execution_strategy")
    if kind == "inference" and strategy not in BROKER_STRATEGIES:
        _fail(boundary, "execution_strategy", "estrategia no permitida")
    if kind == "ingestion":
        for field in ("execution_strategy", "execution_preset", "selection_mode"):
            if payload.get(field) is not None:
                _fail(boundary, field, "debe ser null para tareas de ingesta")
    if status == "completed":
        result = _mapping(payload.get("result"), boundary, "result")
        if kind == "inference":
            assistant_content = result.get("assistant_content", result.get("result_markdown"))
            _string(assistant_content, boundary, "result.assistant_content")
        if kind == "inference" and strategy == "mixture_of_agents":
            consensus = _mapping(result.get("consensus"), boundary, "result.consensus")
            completed = consensus.get("proposers_completed")
            if not isinstance(completed, int) or completed < 2:
                _fail(boundary, "result.consensus.proposers_completed", "debe indicar quorum de al menos 2")
            scheduling = _mapping(result.get("scheduling"), boundary, "result.scheduling")
            if scheduling.get("mode_used") not in {"parallel", "waves", "sequential"}:
                _fail(boundary, "result.scheduling.mode_used", "modo no permitido")
            usage = _mapping(result.get("usage"), boundary, "result.usage")
            if not isinstance(usage.get("invocations"), int) or usage["invocations"] < 3:
                _fail(boundary, "result.usage.invocations", "no corresponde a un consenso completo")
            models = result.get("models_used")
            if not isinstance(models, list) or len(models) < 3:
                _fail(boundary, "result.models_used", "debe contener participantes y árbitro")
        if payload.get("error") is not None:
            _fail(boundary, "error", "debe ser null en completed")
    elif status == "failed":
        error = _mapping(payload.get("error"), boundary, "error")
        _string(error.get("code"), boundary, "error.code")
        if not isinstance(error.get("message"), str):
            _fail(boundary, "error.message", "debe ser string")
        if not isinstance(error.get("retryable"), bool):
            _fail(boundary, "error.retryable", "debe ser boolean")
    elif status == "waiting_for_tools":
        result = _mapping(payload.get("result"), boundary, "result")
        if result.get("status") != "waiting_for_tools":
            _fail(boundary, "result.status", "debe ser waiting_for_tools")
        calls = result.get("pending_tool_calls")
        if not isinstance(calls, list) or not calls:
            _fail(boundary, "result.pending_tool_calls", "debe ser una lista no vacía")
        for index, call in enumerate(calls):
            item = _mapping(call, boundary, f"result.pending_tool_calls[{index}]")
            _string(item.get("id"), boundary, f"result.pending_tool_calls[{index}].id")
            _string(item.get("name"), boundary, f"result.pending_tool_calls[{index}].name")
            _mapping(item.get("arguments"), boundary, f"result.pending_tool_calls[{index}].arguments")
        if strategy == "agent":
            for field in ("agent_iteration", "agent_max_iterations"):
                value = progress.get(field)
                if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                    _fail(boundary, f"progress.{field}", "debe ser integer positivo")
    elif status == "cancelled" and payload.get("result") is not None:
        _fail(boundary, "result", "debe ser null en cancelled")
    return payload


def normalize_capabilities_response(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Normaliza el bloque aditivo de capacidades sin rechazar campos futuros.

    Los campos conocidos con una forma inesperada caen a un valor conservador.
    Así un cambio aditivo o una capacidad opcional mal formada no inutiliza el
    resto de la negociación ni bloquea el envío de tareas.
    """

    boundary = "broker_to_orchestrator_capabilities_v2"
    source = _mapping(payload, boundary, "capabilities")
    normalized = dict(source)

    def string_list(field: str, default: list[str]) -> None:
        value = source.get(field)
        normalized[field] = (
            list(value)
            if isinstance(value, list) and all(isinstance(item, str) and item for item in value)
            else list(default)
        )

    def string_list_map(field: str) -> None:
        value = source.get(field)
        if not isinstance(value, Mapping):
            normalized[field] = {}
            return
        normalized[field] = {
            key: list(items)
            for key, items in value.items()
            if isinstance(key, str)
            and isinstance(items, list)
            and all(isinstance(item, str) and item for item in items)
        }

    string_list("strategies", [])
    string_list("agent_skills", [])
    string_list("work_lanes", ["inference"])
    string_list_map("presets")
    string_list_map("scheduling_by_preset")
    string_list_map("ingestion_formats")

    for field in (
        "derived_data_boundary",
        "sandbox_run_code",
        "file_ingestion",
        "long_context_map_reduce",
    ):
        value = source.get(field)
        normalized[field] = value if isinstance(value, bool) else False

    max_active = source.get("max_active_workflows")
    normalized["max_active_workflows"] = (
        max_active if isinstance(max_active, int) and not isinstance(max_active, bool) and max_active >= 1 else 1
    )
    return normalized


def validate_models_response(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    boundary = "broker_to_orchestrator_v2"
    models = payload.get("models")
    if not isinstance(models, list):
        _fail(boundary, "models", "debe ser una lista")
    validated = []
    for index, model in enumerate(models):
        item = _mapping(model, boundary, f"models[{index}]")
        _string(item.get("name"), boundary, f"models[{index}].name")
        if item.get("status") not in {"available", "loaded", "online", "offline", "unavailable"}:
            _fail(boundary, f"models[{index}].status", "estado no permitido")
        validated.append(item)
    return validated
