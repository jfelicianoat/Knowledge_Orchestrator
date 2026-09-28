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
from dataclasses import dataclass
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
#: Días que un modelo que rompió una tarea con esquema deja de proponerse solo.
FAILURE_VETO_DAYS = 14


@dataclass(frozen=True, slots=True)
class AnalysisPolicy:
    """Qué modelo se pide para una tarea con esquema y con qué margen.

    Antes la extracción declaraba siempre `fallback_allowed=True` y
    `allowed_providers=["ollama"]`, aunque la persona hubiera fijado un modelo de
    LM Studio o prohibido sustituciones en el perfil (auditoría H10).
    """

    model: str | None
    providers: tuple[str, ...]
    exact: bool
    origin: str  # manual | auto | broker

    @property
    def label(self) -> str:
        if self.origin == "manual":
            return f"{self.model} (elegido en Ajustes, sin sustituciones)"
        if self.origin == "auto":
            suffix = "" if not self.exact else ", sin sustituciones"
            return f"{self.model} (elegido por la aplicación{suffix})"
        return "el que elija el Broker"


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
        # El veto caduca: un fallo de hace semanas pudo deberse a una causa ya
        # corregida (le pasó a `granite4.1:30b`), y un veto eterno lo excluía
        # para siempre. Además se puede rehabilitar a mano desde Ajustes.
        rejected = [str(row["model"]) for row in connection.execute(
            "SELECT model FROM analysis_model_failures WHERE last_failed_at >= "
            "strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?)", (f"-{FAILURE_VETO_DAYS} days",))]
    return choose_json_model([dict(row) for row in rows], providers=providers, rejected=rejected)


def pinned_analysis_model(database: Database, *, profile_id: int | None = None) -> str | None:
    """El «modelo para análisis» que la persona fijó en Ajustes, si lo hay.

    Con `profile_id` se lee el de ese perfil —el de la nota que se analiza—; sin
    él (una consulta al conocimiento no pertenece a ninguna nota) vale el primer
    perfil activo que haya fijado uno, que es también el orden que muestra
    Ajustes.
    """

    with closing(database.connect(readonly=True)) as connection:
        if profile_id is not None:
            row = connection.execute(
                "SELECT analysis_model FROM profiles WHERE profile_id = ?", (profile_id,)
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT analysis_model FROM profiles WHERE enabled = 1 AND analysis_model <> '' "
                "ORDER BY profile_id LIMIT 1"
            ).fetchone()
    return str(row["analysis_model"]) or None if row else None


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


def analysis_policy(database: Database, *, profile_id: int | None) -> AnalysisPolicy:
    """La política efectiva de una tarea con esquema para la nota de ese perfil."""

    pinned = pinned_analysis_model(database, profile_id=profile_id)
    substitution_allowed = True
    provider = None
    with closing(database.connect(readonly=True)) as connection:
        if profile_id is not None:
            row = connection.execute(
                "SELECT fallback_allowed FROM profiles WHERE profile_id = ?", (profile_id,)
            ).fetchone()
            substitution_allowed = bool(row["fallback_allowed"]) if row else True
        if pinned:
            found = connection.execute(
                "SELECT provider FROM model_catalog WHERE name = ? ORDER BY provider LIMIT 1", (pinned,)
            ).fetchone()
            provider = str(found["provider"]) if found and found["provider"] else None
    if pinned:
        # Lo que la persona fija se respeta tal cual: su proveedor real, sin
        # que el Broker lo cambie por otro. La privacidad la sigue imponiendo
        # la clasificación local_only de la petición.
        return AnalysisPolicy(pinned, (provider,) if provider else JSON_TASK_PROVIDERS, True, "manual")
    chosen = json_model_from_catalog(database)
    return AnalysisPolicy(chosen, JSON_TASK_PROVIDERS, not substitution_allowed, "auto" if chosen else "broker")


def list_analysis_failures(database: Database) -> list[dict[str, Any]]:
    with closing(database.connect(readonly=True)) as connection:
        rows = connection.execute(
            "SELECT model, error_code, message, failures, last_failed_at, "
            "last_failed_at >= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?) AS vetoed "
            "FROM analysis_model_failures ORDER BY last_failed_at DESC",
            (f"-{FAILURE_VETO_DAYS} days",),
        ).fetchall()
    return [dict(row) for row in rows]


def forget_analysis_failure(database: Database, model: str) -> bool:
    """Rehabilita un modelo vetado: vuelve a poder elegirse solo."""

    with database.transaction(immediate=True) as connection:
        return connection.execute(
            "DELETE FROM analysis_model_failures WHERE model = ?", (model,)
        ).rowcount == 1
