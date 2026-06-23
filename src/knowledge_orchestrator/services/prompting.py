from __future__ import annotations

import math
from typing import Any, Mapping

from knowledge_orchestrator.domain.models import ProfileDefinition


class PromptRenderError(ValueError):
    pass


class PromptRenderer:
    def render(self, template: str, context: Mapping[str, Any]) -> str:
        values = {key: "No disponible" if value is None else str(value) for key, value in context.items()}
        try:
            rendered = template.format_map(values)
        except (KeyError, ValueError) as error:
            raise PromptRenderError(f"No se pudo renderizar el prompt: {error}") from error
        if not rendered.strip():
            raise PromptRenderError("El prompt renderizado está vacío")
        return rendered


def estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


class TextChunker:
    def split(self, text: str, *, max_tokens: int) -> list[str]:
        if max_tokens < 1:
            raise ValueError("max_tokens debe ser positivo")
        if estimate_tokens(text) <= max_tokens:
            return [text]
        max_characters = max_tokens * 4
        chunks: list[str] = []
        current = ""
        for line in text.splitlines(keepends=True):
            for unit in self._split_oversized(line, max_characters):
                if current and len(current) + len(unit) > max_characters:
                    chunks.append(current.rstrip("\n"))
                    current = ""
                current += unit
        if current:
            chunks.append(current.rstrip("\n"))
        return [chunk for chunk in chunks if chunk]

    @staticmethod
    def _split_oversized(value: str, maximum: int) -> list[str]:
        if len(value) <= maximum:
            return [value]
        units: list[str] = []
        remaining = value
        while len(remaining) > maximum:
            boundary = max(
                remaining.rfind(". ", 0, maximum),
                remaining.rfind(" ", 0, maximum),
            )
            cut = boundary + 1 if boundary > maximum // 2 else maximum
            units.append(remaining[:cut])
            remaining = remaining[cut:]
        if remaining:
            units.append(remaining)
        return units


def prompt_context(metadata: Mapping[str, Any], transcript: str, **extra: Any) -> dict[str, Any]:
    context = {
        "title": metadata.get("title"),
        "channel": metadata.get("channel"),
        "transcript": transcript,
        "published_date": metadata.get("published_date"),
        "captured_at": metadata.get("captured_at"),
        "source_type": metadata.get("source_type"),
        "source_url": metadata.get("source_url"),
        "chunk": transcript,
        "chunk_index": extra.get("chunk_index", 1),
        "chunk_count": extra.get("chunk_count", 1),
        "partial_results": extra.get("partial_results", ""),
    }
    context.update(extra)
    return context


def build_chat_request(
    *,
    task_id: str,
    idempotency_key: str,
    workflow_id: str,
    step_id: str,
    profile: ProfileDefinition,
    system_content: str,
    user_content: str,
    execution_step: str,
) -> dict[str, Any]:
    use_consensus = (
        profile.execution_strategy == "mixture_of_agents"
        and execution_step in profile.multitasking_steps
        and execution_step in {"single", "synthesis"}
    )
    strategy = "mixture_of_agents" if use_consensus else "single"
    proposer_count = profile.consensus_max_proposers if use_consensus else 1
    prompt = (
        "<system_instructions>\n"
        + system_content
        + "\n</system_instructions>\n\n<user_request>\n"
        + user_content
        + "\n</user_request>"
    )
    return {
        "idempotency_key": idempotency_key,
        "request_id": task_id,
        "content": {
            "prompt": prompt,
            "attachments": [],
            "metadata": {"workflow_id": workflow_id, "step_id": step_id},
        },
        "output": {"format": "markdown", "json_schema": None, "language": "es"},
        "generation": {
            "temperature": profile.temperature,
            "max_output_tokens": profile.max_output_tokens,
        },
        "model_requirements": {
            "preferred_model": profile.preferred_model,
            "fallback_allowed": profile.fallback_allowed,
            "cloud_allowed": profile.cloud_allowed,
            "allowed_providers": list(profile.allowed_providers),
            "max_cost_usd": profile.max_cost_usd,
        },
        "execution": {
            "strategy": strategy,
            "preset": profile.consensus_preset if use_consensus else "fast",
            "scheduling": "adaptive",
            "max_proposers": proposer_count,
            "max_judges": 0,
            "max_rounds": 1,
            "timeout_seconds": profile.consensus_timeout_seconds if use_consensus else 600,
            "early_stop": True,
            "selection": {
                "mode": "auto",
                "diversity_policy": "different_families",
                "arbiter_policy": "strongest_available",
                "allow_substitution": profile.fallback_allowed,
                "proposers": [],
                "required_proposers": [],
                "proposer_count": proposer_count,
            },
        },
        "risk": {
            "data_classification": profile.data_classification,
            "human_review_required": profile.human_review_required,
        },
        "priority": 100,
    }
