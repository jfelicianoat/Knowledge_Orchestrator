"""Índice de las notas publicadas para recuperar lo relevante a una pregunta.

Hasta el 21-oct-2026 ChatyGPT mandaba al Broker TODAS las notas en cada
pregunta: 89 notas eran ~240k tokens, tardaba 20 minutos y crecía sin techo.
Ahora cada nota se parte en fragmentos que se buscan de dos formas:

- por palabras (FTS5), que acierta con nombres exactos como «MCP»;
- por significado (embeddings del Broker con un único modelo), que acierta con
  sinónimos y con la pregunta formulada de otra manera.

No hay un tope de notas por respuesta (decisión del usuario: prefiere una
respuesta lenta a perder información). La búsqueda devuelve todo lo que
destaca por cualquiera de los dos caminos, y las notas que aún no están
indexadas se devuelven aparte para que el cliente las incluya enteras.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
import uuid
from array import array
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from knowledge_orchestrator.domain.broker_contracts import BrokerContractError, embedding_vectors
from knowledge_orchestrator.domain.knowledge import KnowledgeConflict
from knowledge_orchestrator.integrations.broker_client import BrokerClient, PermanentBrokerError, TransientBrokerError
from knowledge_orchestrator.repositories.database import Database
from knowledge_orchestrator.services.broker_submission import attempt_broker_submission
from knowledge_orchestrator.services.semantic_maintenance.prompts import PromptsMixin, _body_start

#: Unos 300–400 tokens en español: cabe en el contexto de cualquier modelo de
#: embeddings instalado (granite-embedding admite 512) y es una idea por fragmento.
FRAGMENT_CHARS = 1200
#: Prioridad del Broker (menor = antes): la pregunta de alguien que espera pasa
#: delante del indexado masivo dentro del carril de embeddings.
QUESTION_PRIORITY = 1
INDEX_PRIORITY = 100
#: Una palabra que aparece en más de esta fracción de fragmentos no distingue
#: nada. Medido con las 103 notas reales (1.755 fragmentos): con un 20 % pasaban
#: «usar» (11 %) y «sobre» (14 %) y la pregunta por MCP traía 66 notas; «MCP»
#: está en el 4 %.
LEXICAL_MAX_SHARE = 0.05
#: Un fragmento es relevante por significado si su similitud destaca sobre el
#: resto del índice (media + K desviaciones). Es relativo al índice y no al
#: modelo: la escala del coseno cambia mucho de un modelo a otro. Con 2σ las
#: preguntas reales traían 8–25 notas con la buena siempre la primera.
SEMANTIC_SIGMAS = 2.0
#: Lo que entra solo por una palabra rara tiene que parecerse algo a la pregunta
#: (media + 1σ): «notas» o «dicen» encajaban con fragmentos que no tenían que ver.
LEXICAL_GATE_SIGMAS = 1.0
#: Con muy pocos vectores la desviación no dice nada: se devuelven todos.
SEMANTIC_MIN_POPULATION = 10
RRF_K = 60
MAX_ATTEMPTS = 5
BACKOFF_SECONDS = (30.0, 60.0, 120.0, 300.0, 600.0)


@dataclass(frozen=True, slots=True)
class EmbeddingModel:
    provider: str
    deployment: str
    model: str

    @property
    def key(self) -> str:
        return f"{self.provider}/{self.deployment}/{self.model}"

    def target(self) -> dict[str, str]:
        return {"provider": self.provider, "deployment": self.deployment, "model": self.model}


def fragment_note(document: str) -> list[tuple[str, str]]:
    """Parte el cuerpo de una nota en fragmentos `(encabezado, texto)`.

    Se agrupan párrafos seguidos bajo el mismo encabezado hasta FRAGMENT_CHARS,
    y un párrafo más largo se corta por frases (o a la fuerza, si una frase sola
    no cabe). No se descarta texto: lo que no quepa va en el fragmento siguiente.
    """

    body = document[_body_start(document):]
    heading = ""
    blocks: list[tuple[str, str]] = []
    for block in re.split(r"\n\s*\n", body):
        block = block.strip()
        if not block:
            continue
        match = re.match(r"#{1,6}\s+(.+)", block)
        if match:
            heading = match.group(1).strip()
            block = block.split("\n", 1)[1].strip() if "\n" in block else ""
            if not block:
                continue
        for piece in _split_long(block):
            blocks.append((heading, piece))
    fragments: list[tuple[str, str]] = []
    for heading, text in blocks:
        if fragments and fragments[-1][0] == heading and len(fragments[-1][1]) + 2 + len(text) <= FRAGMENT_CHARS:
            fragments[-1] = (heading, fragments[-1][1] + "\n\n" + text)
        else:
            fragments.append((heading, text))
    return fragments


def _split_long(text: str, limit: int = FRAGMENT_CHARS) -> list[str]:
    if len(text) <= limit:
        return [text]
    pieces: list[str] = []
    current = ""
    for sentence in re.split(r"(?<=[.!?…])\s+", text):
        while len(sentence) > limit:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(sentence[:limit])
            sentence = sentence[limit:]
        if current and len(current) + 1 + len(sentence) > limit:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}" if current else sentence
    if current:
        pieces.append(current)
    return pieces


def _pack(vector: list[float]) -> bytes:
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm or not math.isfinite(norm):
        raise ValueError("El vector no tiene una norma válida")
    return array("f", (value / norm for value in vector)).tobytes()


def _unpack(blob: bytes) -> array:
    vector = array("f")
    vector.frombytes(blob)
    return vector


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class NoteIndexService:
    def __init__(self, database: Database, access: Any, capabilities: Callable[[], dict]) -> None:
        self.database = database
        self.access = access
        self.capabilities = capabilities

    # --- Modelo -----------------------------------------------------------------

    def model(self) -> EmbeddingModel | None:
        with closing(self.database.connect(readonly=True)) as connection:
            row = connection.execute(
                "SELECT provider, deployment, model FROM note_index_config WHERE config_id = 1"
            ).fetchone()
        return EmbeddingModel(row["provider"], row["deployment"], row["model"]) if row else None

    def available_models(self) -> list[EmbeddingModel]:
        """Modelos de embeddings locales del catálogo del Broker.

        Solo locales: las notas son del dueño del vault y el índice viaja entero
        al modelo. Un modelo en la nube vería todo el conocimiento.
        """

        models = []
        with closing(self.database.connect(readonly=True)) as connection:
            for row in connection.execute("SELECT name, provider, capabilities_json FROM model_catalog ORDER BY name"):
                try:
                    catalog = json.loads(row["capabilities_json"] or "{}")
                except json.JSONDecodeError:
                    continue
                capabilities = catalog.get("capabilities") or []
                if "embedding" in capabilities and catalog.get("deployment") == "local" \
                        and catalog.get("status") in {"available", "loaded", "online"}:
                    models.append(EmbeddingModel(str(row["provider"]), "local", str(row["name"])))
        return models

    def set_model(self, model: EmbeddingModel) -> None:
        """Cambia el modelo del índice. Los vectores del anterior se borran: no son comparables."""

        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT INTO note_index_config(config_id, provider, deployment, model) VALUES (1, ?, ?, ?) "
                "ON CONFLICT(config_id) DO UPDATE SET provider = excluded.provider, "
                "deployment = excluded.deployment, model = excluded.model, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
                (model.provider, model.deployment, model.model),
            )
            connection.execute("DELETE FROM fragment_embeddings WHERE model_key <> ?", (model.key,))
            connection.execute(
                "UPDATE index_jobs SET status = 'ERROR', error_code = 'MODEL_CHANGED', "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE model_key <> ? AND status IN ('READY', 'QUEUED')",
                (model.key,),
            )

    # --- Fragmentos y lotes -----------------------------------------------------

    def refresh_fragments(self) -> int:
        """Trocea las notas publicadas cuyo contenido vigente aún no tiene fragmentos."""

        with closing(self.database.connect(readonly=True)) as connection:
            pending = connection.execute(
                "SELECT n.note_id FROM notes n WHERE n.status = 'PUBLISHED' AND n.content_hash IS NOT NULL "
                "AND NOT EXISTS (SELECT 1 FROM note_fragments f WHERE f.note_id = n.note_id "
                "AND f.content_hash = n.content_hash) ORDER BY n.note_id"
            ).fetchall()
        done = 0
        for row in pending:
            try:
                document = self.access.document(int(row["note_id"]))
            except (LookupError, KnowledgeConflict):
                # Movida o editada fuera: la reconciliación de KO la resolverá antes.
                continue
            fragments = fragment_note(document["content"])
            with self.database.transaction(immediate=True) as connection:
                connection.execute("DELETE FROM note_fragments WHERE note_id = ?", (row["note_id"],))
                connection.executemany(
                    "INSERT INTO note_fragments(note_id, content_hash, ordinal, heading, text) VALUES (?, ?, ?, ?, ?)",
                    [(row["note_id"], document["content_hash"], ordinal, heading, text)
                     for ordinal, (heading, text) in enumerate(fragments)],
                )
            done += 1
        with self.database.transaction(immediate=True) as connection:
            # Fragmentos de notas despublicadas o de versiones anteriores.
            connection.execute(
                "DELETE FROM note_fragments WHERE fragment_id IN (SELECT f.fragment_id FROM note_fragments f "
                "JOIN notes n ON n.note_id = f.note_id WHERE n.status <> 'PUBLISHED' "
                "OR n.content_hash IS NOT f.content_hash)"
            )
        return done

    def schedule_jobs(self) -> int:
        """Crea lotes para los fragmentos vigentes que no tienen vector del modelo elegido."""

        model = self.model()
        if model is None:
            return 0
        batch_max = self.capabilities().get("embedding_batch_max")
        size = batch_max if isinstance(batch_max, int) and batch_max >= 1 else 1
        with closing(self.database.connect(readonly=True)) as connection:
            busy = {
                fragment_id
                for row in connection.execute(
                    "SELECT fragment_ids_json FROM index_jobs WHERE model_key = ? AND status IN ('READY', 'QUEUED')",
                    (model.key,),
                )
                for fragment_id in json.loads(row["fragment_ids_json"])
            }
            rows = connection.execute(
                "SELECT f.fragment_id, f.note_id, f.content_hash, f.heading, f.text, c.title "
                "FROM note_fragments f JOIN notes n ON n.note_id = f.note_id AND n.content_hash = f.content_hash "
                "JOIN captures c ON c.capture_id = n.capture_id WHERE n.status = 'PUBLISHED' "
                "AND NOT EXISTS (SELECT 1 FROM fragment_embeddings e WHERE e.fragment_id = f.fragment_id "
                "AND e.model_key = ?) ORDER BY f.note_id, f.ordinal",
                (model.key,),
            ).fetchall()
        by_note: dict[tuple[int, str], list[Any]] = {}
        for row in rows:
            if row["fragment_id"] not in busy:
                by_note.setdefault((row["note_id"], row["content_hash"]), []).append(row)
        created = 0
        for (note_id, content_hash), items in by_note.items():
            for start in range(0, len(items), size):
                batch = items[start:start + size]
                job_id = f"index_{note_id}_{uuid.uuid4().hex[:12]}"
                request = PromptsMixin.embedding_batch_request(
                    job_id, [self.embedding_text(item) for item in batch], target=model.target(),
                    priority=INDEX_PRIORITY, batched=size > 1,
                )
                with self.database.transaction(immediate=True) as connection:
                    connection.execute(
                        "INSERT INTO index_jobs(job_id, note_id, content_hash, model_key, fragment_ids_json, "
                        "request_json) VALUES (?, ?, ?, ?, ?, ?)",
                        (job_id, note_id, content_hash, model.key,
                         json.dumps([item["fragment_id"] for item in batch]), json.dumps(request, ensure_ascii=False)),
                    )
                created += 1
        return created

    @staticmethod
    def embedding_text(row: Any) -> str:
        """El título y el encabezado dan contexto: «Instalación» no dice de qué."""

        return "\n".join(part for part in (row["title"], row["heading"], row["text"]) if part)

    def store_vectors(self, job_id: str, vectors: list[list[float]], embedding_model: dict | None) -> None:
        with self.database.transaction(immediate=True) as connection:
            job = connection.execute("SELECT * FROM index_jobs WHERE job_id = ?", (job_id,)).fetchone()
            if job is None or job["status"] != "QUEUED":
                return
            fragment_ids = json.loads(job["fragment_ids_json"])
            if len(vectors) != len(fragment_ids):
                raise ValueError(f"{len(vectors)} vectores para {len(fragment_ids)} fragmentos")
            digest = (embedding_model or {}).get("digest")
            connection.executemany(
                "INSERT INTO fragment_embeddings(fragment_id, model_key, digest, dimensions, vector) "
                "SELECT ?, ?, ?, ?, ? WHERE EXISTS (SELECT 1 FROM note_fragments WHERE fragment_id = ?) "
                "ON CONFLICT(fragment_id, model_key) DO UPDATE SET digest = excluded.digest, "
                "dimensions = excluded.dimensions, vector = excluded.vector",
                [(fragment_id, job["model_key"], digest, len(vector), _pack(vector), fragment_id)
                 for fragment_id, vector in zip(fragment_ids, vectors, strict=True)],
            )
            connection.execute(
                "UPDATE index_jobs SET status = 'SUCCESS', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE job_id = ?", (job_id,),
            )

    def split_fragment(self, job_id: str, index: int) -> None:
        """Un texto no cabía en el modelo: se parte en dos y el lote se vuelve a programar.

        El Broker nunca trunca (devolvería un vector que parece válido y no lo
        es), así que el fragmento se reparte sin perder texto.
        """

        with self.database.transaction(immediate=True) as connection:
            job = connection.execute("SELECT * FROM index_jobs WHERE job_id = ?", (job_id,)).fetchone()
            fragment_ids = json.loads(job["fragment_ids_json"]) if job else []
            if 0 <= index < len(fragment_ids):
                fragment = connection.execute(
                    "SELECT * FROM note_fragments WHERE fragment_id = ?", (fragment_ids[index],)
                ).fetchone()
                if fragment is not None and len(fragment["text"]) > 1:
                    half = len(fragment["text"]) // 2
                    cut = fragment["text"].rfind(" ", 0, half)
                    cut = cut if cut > 0 else half
                    last = connection.execute(
                        "SELECT MAX(ordinal) FROM note_fragments WHERE note_id = ? AND content_hash = ?",
                        (fragment["note_id"], fragment["content_hash"]),
                    ).fetchone()[0]
                    connection.execute("DELETE FROM note_fragments WHERE fragment_id = ?", (fragment["fragment_id"],))
                    connection.executemany(
                        "INSERT INTO note_fragments(note_id, content_hash, ordinal, heading, text) "
                        "VALUES (?, ?, ?, ?, ?)",
                        [(fragment["note_id"], fragment["content_hash"], last + offset, fragment["heading"], text)
                         for offset, text in ((1, fragment["text"][:cut].strip()), (2, fragment["text"][cut:].strip()))
                         if text],
                    )
            connection.execute(
                "UPDATE index_jobs SET status = 'ERROR', error_code = 'EMBEDDING_INPUT_TOO_LONG', "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE job_id = ?", (job_id,),
            )

    def status(self) -> dict[str, Any]:
        model = self.model()
        with closing(self.database.connect(readonly=True)) as connection:
            published = connection.execute("SELECT COUNT(*) FROM notes WHERE status = 'PUBLISHED'").fetchone()[0]
            indexed = connection.execute(
                "SELECT COUNT(*) FROM notes n WHERE n.status = 'PUBLISHED' AND EXISTS (SELECT 1 FROM note_fragments f "
                "WHERE f.note_id = n.note_id AND f.content_hash = n.content_hash) AND NOT EXISTS (SELECT 1 "
                "FROM note_fragments f WHERE f.note_id = n.note_id AND f.content_hash = n.content_hash AND NOT EXISTS "
                "(SELECT 1 FROM fragment_embeddings e WHERE e.fragment_id = f.fragment_id AND e.model_key = ?))",
                (model.key if model else "",),
            ).fetchone()[0] if model else 0
            jobs = dict(connection.execute(
                "SELECT status, COUNT(*) FROM index_jobs WHERE model_key = ? GROUP BY status",
                (model.key if model else "",),
            ).fetchall())
        return {"model": model.target() if model else None, "notes_published": published, "notes_indexed": indexed,
                "jobs_pending": jobs.get("READY", 0) + jobs.get("QUEUED", 0), "jobs_failed": jobs.get("ERROR", 0)}

    # --- Búsqueda ---------------------------------------------------------------

    def search(self, question: str, vector: list[float] | None) -> dict[str, Any]:
        """Todo lo relevante por palabras o por significado, agrupado por nota."""

        model = self.model()
        with closing(self.database.connect(readonly=True)) as connection:
            current = "f.content_hash = n.content_hash AND n.status = 'PUBLISHED'"
            total = connection.execute(
                f"SELECT COUNT(*) FROM note_fragments f JOIN notes n ON n.note_id = f.note_id WHERE {current}"
            ).fetchone()[0]
            lexical = self._lexical(connection, question, total, current)
            semantic: dict[int, float] = {}
            if vector is not None and model:
                similarities = self._similarities(connection, vector, model, current)
                semantic = self._outliers(similarities, SEMANTIC_SIGMAS)
                gate = self._outliers(similarities, LEXICAL_GATE_SIGMAS)
                # Sin vector (fragmento recién partido) no hay con qué filtrar: se queda.
                lexical = {key: value for key, value in lexical.items() if key in gate or key not in similarities}
            scores: dict[int, float] = {}
            for ranking in (lexical, semantic):
                ordered = sorted(ranking, key=lambda key: (-ranking[key], key))
                for position, fragment_id in enumerate(ordered):
                    scores[fragment_id] = scores.get(fragment_id, 0.0) + 1.0 / (RRF_K + position + 1)
            notes: dict[int, dict[str, Any]] = {}
            if scores:
                marks = ",".join("?" * len(scores))
                for row in connection.execute(
                    "SELECT f.fragment_id, f.note_id, f.heading, f.text, c.title FROM note_fragments f "
                    "JOIN notes n ON n.note_id = f.note_id JOIN captures c ON c.capture_id = n.capture_id "
                    f"WHERE f.fragment_id IN ({marks})", list(scores),
                ):
                    note = notes.setdefault(row["note_id"], {"document_id": row["note_id"], "title": row["title"],
                                                             "score": 0.0, "fragments": []})
                    note["score"] = max(note["score"], scores[row["fragment_id"]])
                    note["fragments"].append({
                        "fragment_id": row["fragment_id"], "heading": row["heading"], "text": row["text"],
                        "lexical": row["fragment_id"] in lexical,
                        "similarity": (round(semantic[row["fragment_id"]], 4)
                                       if row["fragment_id"] in semantic else None),
                    })
            unindexed = [row[0] for row in connection.execute(
                "SELECT n.note_id FROM notes n WHERE n.status = 'PUBLISHED' AND (? IS NULL OR NOT EXISTS ("
                "SELECT 1 FROM note_fragments f WHERE f.note_id = n.note_id AND f.content_hash = n.content_hash) "
                "OR EXISTS (SELECT 1 FROM note_fragments f WHERE f.note_id = n.note_id "
                "AND f.content_hash = n.content_hash AND NOT EXISTS (SELECT 1 FROM fragment_embeddings e "
                "WHERE e.fragment_id = f.fragment_id AND e.model_key = ?))) ORDER BY n.note_id",
                (model.key if model else None, model.key if model else ""),
            )]
        for note in notes.values():
            note["fragments"].sort(key=lambda item: -scores[item["fragment_id"]])
        ranked = sorted(notes.values(), key=lambda note: (-note["score"], note["document_id"]))
        return {"documents": ranked, "unindexed_document_ids": [n for n in unindexed if n not in notes],
                "method": "hybrid" if semantic or (vector is not None and model) else "lexical",
                "index": self.status()}

    @staticmethod
    def _lexical(connection: Any, question: str, total: int, current: str) -> dict[int, float]:
        tokens = list(dict.fromkeys(token for token in re.findall(r"\w+", question.casefold()) if len(token) > 1))[:32]
        informative = []
        for token in tokens:
            frequency = connection.execute(
                "SELECT COUNT(*) FROM note_fragments_fts "
                "JOIN note_fragments f ON f.fragment_id = note_fragments_fts.rowid "
                f"JOIN notes n ON n.note_id = f.note_id WHERE note_fragments_fts MATCH ? AND {current}",
                ('"' + token.replace('"', "") + '"',),
            ).fetchone()[0]
            if 0 < frequency <= max(1, LEXICAL_MAX_SHARE * total):
                informative.append(token)
        if not informative:
            return {}
        expression = " OR ".join('"' + token.replace('"', "") + '"' for token in informative)
        # bm25 es menor cuanto mejor: se invierte para que mayor = más relevante.
        return {row[0]: -row[1] for row in connection.execute(
            "SELECT f.fragment_id, bm25(note_fragments_fts) FROM note_fragments_fts "
            "JOIN note_fragments f ON f.fragment_id = note_fragments_fts.rowid JOIN notes n ON n.note_id = f.note_id "
            f"WHERE note_fragments_fts MATCH ? AND {current}", (expression,),
        )}

    @staticmethod
    def _similarities(connection: Any, vector: list[float], model: EmbeddingModel, current: str) -> dict[int, float]:
        # shortcut: coseno en Python puro sobre todo el índice (~0,15 s por 2.000 fragmentos de 1024 dimensiones);
        # pasar a sqlite-vec o numpy cuando el índice supere ~100.000 fragmentos.
        query = _unpack(_pack(vector))
        similarities: dict[int, float] = {}
        for row in connection.execute(
            "SELECT e.fragment_id, e.vector FROM fragment_embeddings e JOIN note_fragments f "
            "ON f.fragment_id = e.fragment_id JOIN notes n ON n.note_id = f.note_id "
            f"WHERE e.model_key = ? AND {current}",
            (model.key,),
        ):
            other = _unpack(row["vector"])
            if len(other) == len(query):
                similarities[row["fragment_id"]] = sum(a * b for a, b in zip(query, other, strict=True))
        return similarities

    @staticmethod
    def _outliers(similarities: dict[int, float], sigmas: float) -> dict[int, float]:
        if len(similarities) < SEMANTIC_MIN_POPULATION:
            return similarities
        values = list(similarities.values())
        threshold = statistics.fmean(values) + sigmas * statistics.pstdev(values)
        return {key: value for key, value in similarities.items() if value >= threshold}

    # --- Consultas durables -----------------------------------------------------

    def create_retrieval(self, question: str, *, owner: str, key: str) -> dict[str, Any]:
        if not 1 <= len(question.strip()) <= 4000:
            raise ValueError("Pregunta inválida")
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        payload_hash = hashlib.sha256(question.encode()).hexdigest()
        with closing(self.database.connect(readonly=True)) as connection:
            previous = connection.execute(
                "SELECT retrieval_id, payload_hash FROM retrievals WHERE owner = ? AND key_hash = ?", (owner, key_hash)
            ).fetchone()
        if previous is not None:
            if previous["payload_hash"] != payload_hash:
                raise KnowledgeConflict("La Idempotency-Key ya se usó con otra pregunta")
            return self.get_retrieval(previous["retrieval_id"], owner=owner)
        retrieval_id = "retrieval_" + uuid.uuid4().hex
        model = self.model()
        request = None
        if model is not None:
            request = PromptsMixin.embedding_batch_request(
                retrieval_id, [question], target=model.target(), priority=QUESTION_PRIORITY, batched=False,
            )
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT INTO retrievals(retrieval_id, owner, key_hash, payload_hash, question, model_key, status, "
                "request_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (retrieval_id, owner, key_hash, payload_hash, question, model.key if model else None,
                 "READY" if request else "SUCCESS", json.dumps(request, ensure_ascii=False) if request else None),
            )
        if request is None:
            # Sin modelo elegido solo hay búsqueda por palabras, y todo cuenta como sin indexar.
            self.complete_retrieval(retrieval_id, None, warning="Sin modelo de embeddings elegido en Ajustes")
        return self.get_retrieval(retrieval_id, owner=owner)

    def complete_retrieval(self, retrieval_id: str, vector: list[float] | None, *, warning: str | None = None) -> None:
        with closing(self.database.connect(readonly=True)) as connection:
            row = connection.execute(
                "SELECT question FROM retrievals WHERE retrieval_id = ?", (retrieval_id,)
            ).fetchone()
        # Una nota publicada hace un momento aún no tiene fragmentos: sin esto, la
        # búsqueda por palabras no la vería hasta el siguiente ciclo del worker.
        self.refresh_fragments()
        result = self.search(row["question"], vector)
        # `degraded` avisa de que faltó la búsqueda por significado: el cliente
        # no debe tomar «no encontrado» como «no está en el conocimiento».
        result["degraded"] = vector is None
        result["warnings"] = [warning] if warning else []
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE retrievals SET status = 'SUCCESS', result_json = ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE retrieval_id = ?",
                (json.dumps(result, ensure_ascii=False), retrieval_id),
            )

    def get_retrieval(self, retrieval_id: str, *, owner: str) -> dict[str, Any]:
        with closing(self.database.connect(readonly=True)) as connection:
            row = connection.execute(
                "SELECT * FROM retrievals WHERE retrieval_id = ? AND owner = ?", (retrieval_id, owner)
            ).fetchone()
        if row is None:
            raise LookupError("Recuperación inexistente")
        payload: dict[str, Any] = {"retrieval_id": row["retrieval_id"], "status": row["status"],
                                   "created_at": row["created_at"], "error_code": row["error_code"]}
        if row["status"] == "SUCCESS":
            payload.update(json.loads(row["result_json"]))
        return payload


class NoteIndexProcessor:
    """Lleva al Broker los lotes del índice y los vectores de las preguntas."""

    def __init__(self, service: NoteIndexService, client: BrokerClient) -> None:
        self.service = service
        self.database = service.database
        self.client = client

    async def cycle(self) -> int:
        self.service.refresh_fragments()
        self.service.schedule_jobs()
        return await self._dispatch("retrievals", "retrieval_id") + await self._dispatch("index_jobs", "job_id") \
            + await self._poll_retrievals() + await self._poll_jobs()

    async def _dispatch(self, table: str, key: str) -> int:
        with closing(self.database.connect(readonly=True)) as connection:
            rows = connection.execute(
                f"SELECT {key} AS id, request_json, attempt FROM {table} WHERE status = 'READY' "
                "AND (next_retry_at IS NULL OR next_retry_at <= ?) ORDER BY created_at", (_now(),),
            ).fetchall()
        accepted = 0
        for row in rows:
            decision = await attempt_broker_submission(
                self.client, row["request_json"], attempt=row["attempt"] + 1, backoff_seconds=BACKOFF_SECONDS,
            )
            with self.database.transaction(immediate=True) as connection:
                if decision.kind == "accepted":
                    connection.execute(
                        f"UPDATE {table} SET status = 'QUEUED', broker_task_id = ?, attempt = attempt + 1, "
                        f"updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE {key} = ?",
                        ((decision.response or {}).get("task_id"), row["id"]),
                    )
                    accepted += 1
                elif decision.kind == "retry":
                    connection.execute(
                        f"UPDATE {table} SET attempt = attempt + 1, next_retry_at = ?, "
                        f"updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE {key} = ?",
                        (decision.retry_at, row["id"]),
                    )
                else:
                    self._fail(connection, table, key, row["id"], decision.code, decision.message or "")
        return accepted

    @staticmethod
    def _fail(connection: Any, table: str, key: str, row_id: str, code: str, message: str) -> None:
        extra = ", error_message = ?" if table == "index_jobs" else ""
        connection.execute(
            f"UPDATE {table} SET status = 'ERROR', error_code = ?{extra}, "
            f"updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE {key} = ?",
            (code, message[:500], row_id) if extra else (code, row_id),
        )

    async def _task(self, task_id: str) -> dict | None:
        try:
            return await self.client.get_task(task_id)
        except TransientBrokerError:
            return None

    async def _poll_jobs(self) -> int:
        with closing(self.database.connect(readonly=True)) as connection:
            rows = connection.execute(
                "SELECT job_id, broker_task_id, attempt FROM index_jobs WHERE status = 'QUEUED' ORDER BY created_at"
            ).fetchall()
        updated = 0
        for row in rows:
            try:
                payload = await self._task(row["broker_task_id"])
            except (PermanentBrokerError, BrokerContractError) as error:
                with self.database.transaction(immediate=True) as connection:
                    self._fail(connection, "index_jobs", "job_id", row["job_id"],
                               "CONTRACT_VALIDATION_FAILED", str(error))
                updated += 1
                continue
            if payload is None or payload.get("status") not in {"completed", "failed", "cancelled"}:
                continue
            updated += 1
            if payload["status"] == "completed":
                result = payload.get("result") or {}
                vectors = embedding_vectors(result)
                with closing(self.database.connect(readonly=True)) as connection:
                    expected = len(json.loads(connection.execute(
                        "SELECT fragment_ids_json FROM index_jobs WHERE job_id = ?", (row["job_id"],)
                    ).fetchone()[0]))
                if len(vectors) != expected:
                    with self.database.transaction(immediate=True) as connection:
                        self._fail(connection, "index_jobs", "job_id", row["job_id"], "EMBEDDING_COUNT_MISMATCH",
                                   f"{len(vectors)} vectores para {expected} fragmentos")
                    continue
                self.service.store_vectors(row["job_id"], vectors, result.get("embedding_model"))
                continue
            failure = payload.get("error") or {}
            if failure.get("code") == "EMBEDDING_INPUT_TOO_LONG":
                index = (failure.get("details") or {}).get("index")
                self.service.split_fragment(row["job_id"], index if isinstance(index, int) else -1)
                continue
            with self.database.transaction(immediate=True) as connection:
                if failure.get("retryable") and row["attempt"] < MAX_ATTEMPTS:
                    retry_at = datetime.now(timezone.utc) + timedelta(seconds=BACKOFF_SECONDS[row["attempt"] - 1])
                    connection.execute(
                        "UPDATE index_jobs SET status = 'READY', broker_task_id = NULL, next_retry_at = ?, "
                        "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE job_id = ?",
                        (retry_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), row["job_id"]),
                    )
                else:
                    self._fail(connection, "index_jobs", "job_id", row["job_id"],
                               str(failure.get("code") or payload["status"].upper()),
                               str(failure.get("message") or ""))
        return updated

    async def _poll_retrievals(self) -> int:
        with closing(self.database.connect(readonly=True)) as connection:
            rows = connection.execute(
                "SELECT retrieval_id, broker_task_id FROM retrievals WHERE status = 'QUEUED' ORDER BY created_at"
            ).fetchall()
        updated = 0
        for row in rows:
            try:
                payload = await self._task(row["broker_task_id"])
            except (PermanentBrokerError, BrokerContractError) as error:
                payload = {"status": "failed", "error": {"code": "CONTRACT_VALIDATION_FAILED", "message": str(error)}}
            if payload is None or payload.get("status") not in {"completed", "failed", "cancelled"}:
                continue
            updated += 1
            vector = None
            warning = None
            if payload["status"] == "completed":
                try:
                    vector = embedding_vectors(payload.get("result") or {})[0]
                except BrokerContractError as error:
                    warning = str(error)
            else:
                warning = f"No se pudo vectorizar la pregunta: {(payload.get('error') or {}).get('code')}"
            self.service.complete_retrieval(row["retrieval_id"], vector, warning=warning)
        return updated
