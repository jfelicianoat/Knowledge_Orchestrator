"""Políticas explícitas: umbrales y ámbitos no sustituyen evidencia ni guardas."""
from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass

from knowledge_orchestrator.domain.knowledge import KnowledgeConflict
from knowledge_orchestrator.domain.monitoring import ROLES


class AutomationDenied(KnowledgeConflict):
    def __init__(self, code: str, reasons: list[str] | None = None):
        self.code = code
        self.reasons = reasons or [code]
        super().__init__(code)


class AutomationPlanTooLarge(ValueError):
    def __init__(self) -> None:
        super().__init__('La simulación supera 8 MiB; selecciona menos propuestas')


@dataclass(frozen=True)
class AutomationPolicyConfig:
    name: str
    source_ids: tuple[int, ...]
    source_kinds: tuple[str, ...] = ('web', 'rss')
    source_roles: tuple[str, ...] = ('official_documentation', 'official_repository')
    relations: tuple[str, ...] = ('SUPERSEDES',)
    claim_types: tuple[str, ...] = ('VERSION',)
    min_source_trust: int = 80
    min_confidence: float = 0.95
    max_claims_per_task: int = 1
    max_notes_per_task: int = 1
    max_tasks_per_run: int = 5
    max_tasks_per_day: int = 20

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not 1 <= len(self.name.strip()) <= 200:
            raise ValueError('La política requiere un nombre de hasta 200 caracteres')
        if not isinstance(self.source_ids, (list, tuple)) or not 1 <= len(self.source_ids) <= 1000 \
                or any(type(identifier) is not int or identifier <= 0 for identifier in self.source_ids):
            raise ValueError('Selecciona explícitamente entre 1 y 1000 fuentes; no se admite ámbito global')
        object.__setattr__(self, 'source_ids', tuple(sorted(set(self.source_ids))))
        for field, allowed in (('source_kinds', {'web', 'rss'}), ('source_roles', set(ROLES)),
                               ('relations', {'SUPERSEDES', 'EXTENDS'}), ('claim_types', None)):
            values = getattr(self, field)
            if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= 100 \
                    or any(not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_]{1,64}', value)
                           or (allowed is not None and value not in allowed) for value in values):
                raise ValueError(f'Condiciones inválidas: {field}')
            object.__setattr__(self, field, tuple(sorted(set(values))))
        for field, maximum in (('min_source_trust', 100), ('max_claims_per_task', 1000),
                               ('max_notes_per_task', 1000), ('max_tasks_per_run', 1000),
                               ('max_tasks_per_day', 10000)):
            value = getattr(self, field)
            minimum = 0 if field == 'min_source_trust' else 1
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f'Límite inválido: {field}')
        if type(self.min_confidence) not in {float, int} or not math.isfinite(self.min_confidence) \
                or not 0 <= self.min_confidence <= 1:
            raise ValueError('Confianza mínima entre 0 y 1')
        if self.max_tasks_per_run > self.max_tasks_per_day:
            raise ValueError('El límite por ejecución no puede superar el límite diario')

    def json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, ensure_ascii=False, allow_nan=False)
