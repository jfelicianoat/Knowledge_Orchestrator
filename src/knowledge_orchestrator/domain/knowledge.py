"""Vigencia explícita; CURRENT no implica que una afirmación esté verificada."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class KnowledgeState(str, Enum):
    CURRENT = 'CURRENT'
    HISTORICAL = 'HISTORICAL'
    SUPERSEDED = 'SUPERSEDED'
    DISPUTED = 'DISPUTED'
    UNCERTAIN = 'UNCERTAIN'
    REVIEW_REQUIRED = 'REVIEW_REQUIRED'


@dataclass(frozen=True, slots=True)
class Entity:
    entity_id: int
    name: str
    entity_key: str


class KnowledgeConflict(ValueError):
    """Una decisión dejó de ser aplicable; requiere nueva revisión."""
