"""Elección de modelo para las tareas que exigen JSON conforme a un esquema.

Extraer afirmaciones, comparar evidencia y responder una consulta fundamentada
piden al Broker un JSON estricto. Un modelo con razonamiento antepone su cadena
de pensamiento y la respuesta deja de ser ese JSON: contra el Broker real, la
extracción falló con `SEMANTIC_CONTRACT_FAILED` («el Broker no devolvió JSON
semántico estricto») usando un modelo que declara `thinking`.

El catálogo ya trae lo necesario para evitarlo: `capabilities` dice quién razona
y `compatibility`/`quarantined`, quién no sirve. Se elige el primero utilizable
por orden alfabético —determinista y explicable— y, si no hay ninguno, se
devuelve `None`, que significa «que elija el Broker»: mejor su criterio que
imponer un modelo que sabemos inadecuado.
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from contextlib import closing
from typing import Any

from knowledge_orchestrator.repositories.database import Database

#: Las peticiones semánticas fijan `allowed_providers: ["ollama"]`; proponer un
#: modelo de otro proveedor sería pedir algo que la propia petición prohíbe.
JSON_TASK_PROVIDERS: tuple[str, ...] = ("ollama",)
#: Modelos entrenados para otra cosa. El primer criterio fue «el primero por
#: orden alfabético» y eligió `glm-ocr:latest`, un OCR de 1.1B: determinista,
#: pero inservible para extraer afirmaciones con un esquema.
SPECIALISED_MARKERS: tuple[str, ...] = (
    "ocr", "coder", "code", "embed", "rerank", "guard", "whisper", "tts", "diffusion", "vision", "moderation",
)
#: Por encima de esto, la latencia local no compensa para una tarea de apoyo.
MAX_PARAMETERS_B = 40.0


def _catalog_of(row: Mapping[str, Any]) -> Mapping[str, Any]:
    catalog = row.get("capabilities_json")
    if isinstance(catalog, str):
        try:
            catalog = json.loads(catalog)
        except json.JSONDecodeError:
            catalog = {}
    return catalog if isinstance(catalog, Mapping) else {}


def _parameters_b(catalog: Mapping[str, Any]) -> float:
    raw = str(catalog.get("parameter_size") or "").strip().upper().removesuffix("B")
    try:
        return float(raw)
    except ValueError:
        return 0.0


def choose_json_model(
    rows: Iterable[Mapping[str, Any]],
    *,
    providers: Sequence[str] = JSON_TASK_PROVIDERS,
    rejected: Sequence[str] = (),
) -> str | None:
    """Modelo de propósito general sin razonamiento. `None` deja la elección al Broker.

    Se descarta lo que no sirve (razona, incompatible, en cuarentena, de otro
    proveedor o entrenado para otra tarea) y entre el resto se prefiere el que
    declara `tools` —señal de que sigue instrucciones estructuradas— y el mayor
    que no pase de `MAX_PARAMETERS_B`, porque en local un modelo enorme
    convierte una tarea de apoyo en una espera larga. A igualdad, orden
    alfabético, para que la elección sea reproducible.
    """

    vetoed = set(rejected)
    candidates: list[tuple[int, float, str]] = []
    for row in rows:
        if str(row.get("name") or "") in vetoed:
            continue  # ya falló una extracción: no se vuelve a proponer solo
        catalog = _catalog_of(row)
        if catalog.get("quarantined") or catalog.get("compatibility") == "incompatible":
            continue
        provider = str(row.get("provider") or catalog.get("provider") or "")
        if providers and provider not in providers:
            continue
        declared = catalog.get("capabilities")
        capabilities: list[str] = [str(item) for item in declared] if isinstance(declared, list) else []
        if "thinking" in capabilities:
            continue
        name = str(row.get("name") or "")
        if not name:
            continue
        haystack = f"{name} {catalog.get('family') or ''}".lower()
        if any(marker in haystack for marker in SPECIALISED_MARKERS):
            continue
        if capabilities and "completion" not in capabilities:
            continue
        size = _parameters_b(catalog)
        candidates.append((1 if "tools" in capabilities else 0, size if size <= MAX_PARAMETERS_B else 0.0, name))
    if not candidates:
        return None
    best = max(candidates, key=lambda item: (item[0], item[1], [-ord(c) for c in item[2]]))
    return best[2]


def json_model_from_catalog(
    database: Database,
    *,
    providers: Sequence[str] = JSON_TASK_PROVIDERS,
    chosen: str | None = None,
) -> str | None:
    """Modelo para una tarea con esquema: manda lo elegido en Ajustes.

    `chosen` es la decisión de la persona y no se discute: solo cuando está
    vacía se elige del catálogo, excluyendo lo que ya falló alguna extracción.
    """

    if chosen:
        return chosen
    with closing(database.connect(readonly=True)) as connection:
        rows = connection.execute(
            "SELECT name, provider, capabilities_json FROM model_catalog "
            "WHERE status IN ('available', 'loaded', 'online') ORDER BY name COLLATE NOCASE"
        ).fetchall()
        rejected = [str(row["model"]) for row in connection.execute(
            "SELECT model FROM analysis_model_failures")]
    return choose_json_model([dict(row) for row in rows], providers=providers, rejected=rejected)


def record_analysis_failure(database: Database, model: str, code: str, message: str) -> None:
    """Apunta el modelo que rompió una tarea con esquema para no reelegirlo."""

    if not model:
        return
    with database.transaction(immediate=True) as connection:
        connection.execute(
            "INSERT INTO analysis_model_failures(model, error_code, message) VALUES (?, ?, ?) "
            "ON CONFLICT(model) DO UPDATE SET failures = failures + 1, error_code = excluded.error_code, "
            "message = excluded.message, last_failed_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')",
            (model, code, message[:500]),
        )
