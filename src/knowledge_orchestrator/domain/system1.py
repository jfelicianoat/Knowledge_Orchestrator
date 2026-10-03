"""Contrato de juicios síncronos 2.11, independiente de las tareas generativas."""
from __future__ import annotations

import math
import re
from typing import Any


def validate_judgment_request(payload: dict[str, Any]) -> None:
    allowed = {'use_case', 'input', 'decision_type', 'options', 'criteria', 'rubric',
               'instructions', 'threshold_profile', 'cloud_allowed'}
    if set(payload) - allowed or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', payload.get('use_case', '')):
        raise ValueError('Petición System 1 inválida')
    if not isinstance(payload.get('input'), dict) or not payload['input']:
        raise ValueError('System 1 requiere input no vacío')
    kind = payload.get('decision_type')
    if kind not in {'binary', 'choice', 'score'} or type(payload.get('cloud_allowed', False)) is not bool:
        raise ValueError('Tipo de juicio o frontera inválidos')
    for field, maximum in (('instructions', 4000), ('threshold_profile', 128)):
        value = payload.get(field)
        if value is not None and (not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum):
            raise ValueError('Instrucción o perfil System 1 inválidos')
    for field in ('options', 'rubric'):
        values = payload.get(field, [])
        applicable = kind == ('choice' if field == 'options' else 'score')
        if not isinstance(values, list) or (not applicable and values):
            raise ValueError('Dominio incompatible con el juicio')
        if applicable and (not 2 <= len(values) <= 20 or any(
                not isinstance(v, str) or not v.strip() for v in values)):
            raise ValueError('Dominio System 1 inválido')
        if field == 'options' and len(set(values)) != len(values):
            raise ValueError('Opciones repetidas')
    criteria = payload.get('criteria', {})
    if not isinstance(criteria, dict) or (criteria and (kind != 'choice' or set(criteria) != set(payload['options']))):
        raise ValueError('Criterios incompatibles')
    if any(not isinstance(v, str) or not v.strip() for v in criteria.values()):
        raise ValueError('Criterios inválidos')


def _score(value: Any) -> bool:
    return type(value) in {int, float} and math.isfinite(value) and 0 <= value <= 1


def validate_judgment(payload: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    if payload.get('use_case') != request['use_case'] or type(payload.get('accepted')) is not bool:
        raise ValueError('Juicio System 1 sin contrato de aceptación')
    if type(payload.get('fallback_used')) is not bool or type(payload.get('confidence_is_calibrated')) is not bool:
        raise ValueError('Metadatos de juicio inválidos')
    for field in ('provider', 'model', 'reason_code'):
        value = payload.get(field)
        if value is not None and (not isinstance(value, str) or not value):
            raise ValueError('Metadatos de proveedor inválidos')
    latency: Any = payload.get('latency_ms')
    if type(latency) not in {int, float} or not math.isfinite(latency) or latency < 0:
        raise ValueError('Latencia System 1 inválida')
    attempts = payload.get('attempts')
    if not isinstance(attempts, list) or any(not isinstance(v, dict) for v in attempts):
        raise ValueError('Intentos System 1 inválidos')
    if payload['accepted'] is False:
        if payload.get('decision') is not None or payload.get('confidence') is not None:
            raise ValueError('Juicio rechazado con decisión')
        return payload
    decision, confidence = payload.get('decision'), payload.get('confidence')
    kind = request['decision_type']
    def in_domain(value: Any) -> bool:
        if kind == 'binary':
            return type(value) is bool
        if kind == 'choice':
            return isinstance(value, str) and value in request['options']
        return (type(value) in {int, float} and math.isfinite(value) and
                float(value).is_integer() and 0 <= value < len(request['rubric']))
    if not in_domain(decision) or not _score(confidence):
        raise ValueError('Decisión o confianza System 1 inválidas')
    alternatives = payload.get('alternatives')
    if not isinstance(alternatives, list) or any(
            not isinstance(a, dict) or not in_domain(a.get('value')) or not _score(a.get('confidence'))
            for a in alternatives):
        raise ValueError('Alternativas System 1 inválidas')
    values = [decision, *(a['value'] for a in alternatives)]
    expected = 2 if kind == 'binary' else len(request['options'] if kind == 'choice' else request['rubric'])
    if len(values) != expected or len(set(values)) != expected or any(
            a['confidence'] > confidence for a in alternatives):
        raise ValueError('Dominio incompleto o top1 inválido')
    return payload
