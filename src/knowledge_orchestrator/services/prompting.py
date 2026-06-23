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
    max_cost_usd: float = 0.05,
) -> dict[str, Any]:
    return {
        "contract_version": "1.0",
        "task_id": task_id,
        "idempotency_key": idempotency_key,
        "routing": {
            "preferred_model": profile.preferred_model,
            "fallback_allowed": profile.fallback_allowed,
            "quality_priority": "high",
            "max_cost_usd": max_cost_usd,
        },
        "inference": {
            "kind": "chat",
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ],
            "temperature": profile.temperature,
            "max_output_tokens": profile.max_output_tokens,
            "response_format": "text",
        },
        "client_context": {"workflow_id": workflow_id, "step_id": step_id},
    }
