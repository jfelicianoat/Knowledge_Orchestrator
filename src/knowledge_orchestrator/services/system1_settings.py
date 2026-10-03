"""Configuración opt-in local: state/system1.json, sobreescrita por KO_SYSTEM1_*."""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, fields
from pathlib import Path


@dataclass(frozen=True, slots=True)
class System1Settings:
    rag_enabled: bool = False
    transcript_enabled: bool = False
    shadow_mode: bool = False
    require_calibrated: bool = False
    http_timeout_seconds: float = 75.0
    stage_timeout_seconds: float = 90.0
    relevance_keep: float = 0.80
    relevance_uncertain: float = 0.55
    rag_min_confidence: float = 0.85
    min_chunks: int = 2
    max_chunks: int = 8
    context_tokens: int = 6000
    transcript_min_confidence: float = 0.90
    segment_tokens: int = 600
    max_segments: int = 64
    adjacent_segments: int = 1

    def __post_init__(self) -> None:
        for item in fields(self):
            value, default = getattr(self, item.name), item.default
            if isinstance(default, bool):
                if type(value) is not bool:
                    raise ValueError(f'{item.name}: se requiere booleano')
            elif type(value) not in {int, float} or not math.isfinite(value) or (
                    isinstance(default, int) and type(value) is not int):
                raise ValueError(f'{item.name}: número inválido')
        for name in ('relevance_keep', 'relevance_uncertain', 'rag_min_confidence', 'transcript_min_confidence'):
            if not 0 <= getattr(self, name) <= 1:
                raise ValueError(f'{name}: fuera de [0,1]')
        if not 1 <= self.min_chunks <= self.max_chunks <= 24 or self.context_tokens < 1:
            raise ValueError('Presupuesto RAG inválido')
        if self.relevance_uncertain > self.relevance_keep:
            raise ValueError('Umbrales de relevancia invertidos')
        if min(self.http_timeout_seconds, self.stage_timeout_seconds, self.segment_tokens, self.max_segments) <= 0:
            raise ValueError('Tiempo o segmentación inválidos')
        if self.adjacent_segments < 0:
            raise ValueError('Contexto adyacente inválido')


def load_system1_settings(state: Path) -> System1Settings:
    path = state / 'system1.json'
    values = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    known = {item.name: item for item in fields(System1Settings)}
    if not isinstance(values, dict) or set(values) - set(known):
        raise ValueError('Configuración System 1 inválida')
    for name, item in known.items():
        raw = os.environ.get('KO_SYSTEM1_' + name.upper())
        if raw is None:
            continue
        if isinstance(item.default, bool):
            if raw.lower() not in {'true', 'false', '1', '0'}:
                raise ValueError(f'KO_SYSTEM1_{name.upper()}: booleano inválido')
            values[name] = raw.lower() in {'true', '1'}
        else:
            values[name] = int(raw) if isinstance(item.default, int) else float(raw)
    return System1Settings(**values)
