from __future__ import annotations

from string import Formatter

from .models import ProfileDefinition

COMMON_PLACEHOLDERS = {
    "title",
    "channel",
    "transcript",
    "published_date",
    "captured_at",
    "source_type",
    "source_url",
}
PROMPT_PLACEHOLDERS = {
    "system_prompt": COMMON_PLACEHOLDERS,
    "user_prompt": COMMON_PLACEHOLDERS,
    "chunk_prompt": COMMON_PLACEHOLDERS | {"chunk", "chunk_index", "chunk_count"},
    "synthesis_prompt": COMMON_PLACEHOLDERS | {"partial_results", "chunk_count"},
}
REQUIRED_PLACEHOLDERS = {
    "user_prompt": {"transcript"},
    "chunk_prompt": {"chunk"},
    "synthesis_prompt": {"partial_results"},
}


class ProfileValidationError(ValueError):
    pass


def prompt_fields(template: str, field_name: str) -> set[str]:
    try:
        fields: set[str] = set()
        for _literal, name, format_spec, conversion in Formatter().parse(template):
            if not name:
                continue
            if "." in name or "[" in name or "]" in name:
                raise ProfileValidationError(f"{field_name}: solo se permiten placeholders simples")
            if format_spec or conversion:
                raise ProfileValidationError(f"{field_name}: formatos y conversiones no están permitidos")
            fields.add(name)
    except ValueError as error:
        if isinstance(error, ProfileValidationError):
            raise
        raise ProfileValidationError(f"{field_name}: plantilla inválida: {error}") from error
    unknown = fields - PROMPT_PLACEHOLDERS[field_name]
    if unknown:
        raise ProfileValidationError(f"{field_name}: placeholders no permitidos: {sorted(unknown)}")
    missing = REQUIRED_PLACEHOLDERS.get(field_name, set()) - fields
    if missing:
        raise ProfileValidationError(f"{field_name}: faltan placeholders: {sorted(missing)}")
    return fields


def validate_profile(profile: ProfileDefinition) -> ProfileDefinition:
    if not profile.name.strip() or len(profile.name) > 100:
        raise ProfileValidationError("name debe contener entre 1 y 100 caracteres")
    if not profile.preferred_model.strip() or len(profile.preferred_model) > 200:
        raise ProfileValidationError("preferred_model debe contener entre 1 y 200 caracteres")
    if not 0 <= profile.temperature <= 2:
        raise ProfileValidationError("temperature debe estar entre 0 y 2")
    if not 1 <= profile.max_output_tokens <= 100_000:
        raise ProfileValidationError("max_output_tokens debe estar entre 1 y 100000")
    if profile.revision < 1:
        raise ProfileValidationError("revision debe ser mayor o igual que 1")
    # "auto" delega en el meta-router del Broker (contrato v2.5): decide entre
    # single, mixture o agent por tarea y aprende de escalados previos. La
    # estrategia "agent" no se expone como valor de perfil a propósito: las
    # skills del Broker (web_search, run_code...) no aplican al flujo de
    # conocimiento y auto ya puede elegirla si conviene.
    if profile.execution_strategy not in {"single", "mixture_of_agents", "auto"}:
        raise ProfileValidationError("execution_strategy no permitido")
    allowed_steps = {"single", "synthesis"}
    if not profile.multitasking_steps or set(profile.multitasking_steps) - allowed_steps:
        raise ProfileValidationError("multitasking_steps solo admite single y synthesis")
    if len(set(profile.multitasking_steps)) != len(profile.multitasking_steps):
        raise ProfileValidationError("multitasking_steps contiene duplicados")
    if profile.consensus_preset != "fast":
        raise ProfileValidationError("solo se admite consensus_preset fast en esta fase")
    if not 2 <= profile.consensus_max_proposers <= 5:
        raise ProfileValidationError("consensus_max_proposers debe estar entre 2 y 5")
    if not 1 <= profile.consensus_timeout_seconds <= 3600:
        raise ProfileValidationError("consensus_timeout_seconds debe estar entre 1 y 3600")
    if profile.data_classification not in {"public", "internal", "confidential", "local_only"}:
        raise ProfileValidationError("data_classification no permitida")
    if not profile.allowed_providers or any(not provider.strip() for provider in profile.allowed_providers):
        raise ProfileValidationError("allowed_providers debe ser una lista no vacía")
    cloud_providers = {"deepseek", "ollama_cloud", "openai", "anthropic", "google"}
    lowered_providers = {provider.lower() for provider in profile.allowed_providers}
    if not profile.cloud_allowed and cloud_providers.intersection(lowered_providers):
        raise ProfileValidationError("cloud_allowed=false no permite proveedores cloud")
    if profile.data_classification == "local_only":
        if profile.cloud_allowed or set(provider.lower() for provider in profile.allowed_providers) != {"ollama"}:
            raise ProfileValidationError("local_only exige cloud desactivado y proveedor ollama")
    if profile.max_cost_usd < 0:
        raise ProfileValidationError("max_cost_usd no puede ser negativo")
    for field_name in PROMPT_PLACEHOLDERS:
        template = getattr(profile, field_name)
        if not template.strip():
            raise ProfileValidationError(f"{field_name} no puede estar vacío")
        prompt_fields(template, field_name)
    return profile
