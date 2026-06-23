from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import date

from knowledge_orchestrator.domain.models import (
    ProfileDefinition,
    SourceOrigin,
    TopicDefinition,
)

from .database import Database


def _profile(row: sqlite3.Row) -> ProfileDefinition:
    return ProfileDefinition(
        profile_id=row["profile_id"],
        name=row["name"],
        system_prompt=row["system_prompt"],
        user_prompt=row["user_prompt"],
        chunk_prompt=row["chunk_prompt"],
        synthesis_prompt=row["synthesis_prompt"],
        preferred_model=row["preferred_model"],
        fallback_allowed=bool(row["fallback_allowed"]),
        temperature=float(row["temperature"]),
        max_output_tokens=int(row["max_output_tokens"]),
        enabled=bool(row["enabled"]),
        revision=int(row["revision"]),
    )


def _topic(row: sqlite3.Row) -> TopicDefinition:
    keywords = json.loads(row["keywords_json"])
    if not isinstance(keywords, list) or not all(isinstance(value, str) for value in keywords):
        raise ValueError(f"keywords_json inválido para topic_id={row['topic_id']}")
    return TopicDefinition(
        topic_id=row["topic_id"],
        name=row["name"],
        folder=row["folder"],
        keywords=tuple(keywords),
        position=row["position"],
        default_profile_id=row["default_profile_id"],
        is_updatable=bool(row["is_updatable"]),
        obsolescence_days=row["obsolescence_days"],
        auto_review=bool(row["auto_review"]),
        enabled=bool(row["enabled"]),
    )


class DomainRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def get_profile(self, profile_id: int) -> ProfileDefinition | None:
        with closing(self.database.connect()) as connection:
            row = connection.execute("SELECT * FROM profiles WHERE profile_id = ?", (profile_id,)).fetchone()
            return _profile(row) if row else None

    def list_profiles(self, *, enabled_only: bool = False) -> list[ProfileDefinition]:
        query = "SELECT * FROM profiles"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY name COLLATE NOCASE, profile_id"
        with closing(self.database.connect()) as connection:
            return [_profile(row) for row in connection.execute(query).fetchall()]

    def enabled_topic_usage_count(self, profile_id: int) -> int:
        with closing(self.database.connect()) as connection:
            return int(connection.execute(
                "SELECT COUNT(*) FROM topics WHERE default_profile_id = ? AND enabled = 1",
                (profile_id,),
            ).fetchone()[0])

    def save_profile(self, profile: ProfileDefinition) -> ProfileDefinition:
        with self.database.transaction(immediate=True) as connection:
            if profile.profile_id is None:
                cursor = connection.execute(
                    "INSERT INTO profiles (name, config_json, system_prompt, user_prompt, chunk_prompt, "
                    "synthesis_prompt, preferred_model, fallback_allowed, temperature, max_output_tokens, "
                    "enabled, revision) VALUES (?, '{}', ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
                    (
                        profile.name,
                        profile.system_prompt,
                        profile.user_prompt,
                        profile.chunk_prompt,
                        profile.synthesis_prompt,
                        profile.preferred_model,
                        int(profile.fallback_allowed),
                        profile.temperature,
                        profile.max_output_tokens,
                        int(profile.enabled),
                    ),
                )
                profile_id = int(cursor.lastrowid)
            else:
                cursor = connection.execute(
                    "UPDATE profiles SET name = ?, system_prompt = ?, user_prompt = ?, chunk_prompt = ?, "
                    "synthesis_prompt = ?, preferred_model = ?, fallback_allowed = ?, temperature = ?, "
                    "max_output_tokens = ?, enabled = ?, revision = revision + 1, "
                    "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                    "WHERE profile_id = ? AND revision = ?",
                    (
                        profile.name,
                        profile.system_prompt,
                        profile.user_prompt,
                        profile.chunk_prompt,
                        profile.synthesis_prompt,
                        profile.preferred_model,
                        int(profile.fallback_allowed),
                        profile.temperature,
                        profile.max_output_tokens,
                        int(profile.enabled),
                        profile.profile_id,
                        profile.revision,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("Perfil modificado por otra operación o inexistente")
                profile_id = profile.profile_id
        saved = self.get_profile(profile_id)
        if saved is None:
            raise RuntimeError("No se pudo recuperar el perfil guardado")
        return saved

    def get_topic(self, topic_id: int) -> TopicDefinition | None:
        with closing(self.database.connect()) as connection:
            row = connection.execute("SELECT * FROM topics WHERE topic_id = ?", (topic_id,)).fetchone()
            return _topic(row) if row else None

    def get_inbox_topic(self) -> TopicDefinition:
        with closing(self.database.connect()) as connection:
            row = connection.execute("SELECT * FROM topics WHERE name = '_inbox'").fetchone()
            if row is None:
                raise RuntimeError("Falta el tema reservado _inbox")
            return _topic(row)

    def list_topics(self, *, enabled_only: bool = False) -> list[TopicDefinition]:
        query = "SELECT * FROM topics"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY position, topic_id"
        with closing(self.database.connect()) as connection:
            return [_topic(row) for row in connection.execute(query).fetchall()]

    def save_topic(self, topic: TopicDefinition) -> TopicDefinition:
        with self.database.transaction(immediate=True) as connection:
            profile = connection.execute(
                "SELECT enabled FROM profiles WHERE profile_id = ?", (topic.default_profile_id,)
            ).fetchone()
            if profile is None:
                raise ValueError("El perfil predeterminado no existe")
            if not bool(profile["enabled"]):
                raise ValueError("El perfil predeterminado está deshabilitado")
            values = (
                topic.name,
                topic.position,
                topic.folder,
                topic.default_profile_id,
                json.dumps(list(topic.keywords), ensure_ascii=False),
                int(topic.is_updatable),
                topic.obsolescence_days,
                int(topic.auto_review),
                int(topic.enabled),
            )
            if topic.topic_id is None:
                cursor = connection.execute(
                    "INSERT INTO topics (name, position, folder, config_json, default_profile_id, "
                    "keywords_json, is_updatable, obsolescence_days, auto_review, enabled) "
                    "VALUES (?, ?, ?, '{}', ?, ?, ?, ?, ?, ?)",
                    values,
                )
                topic_id = int(cursor.lastrowid)
            else:
                cursor = connection.execute(
                    "UPDATE topics SET name = ?, position = ?, folder = ?, default_profile_id = ?, "
                    "keywords_json = ?, is_updatable = ?, obsolescence_days = ?, auto_review = ?, "
                    "enabled = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                    "WHERE topic_id = ?",
                    (*values, topic.topic_id),
                )
                if cursor.rowcount != 1:
                    raise ValueError("El tema no existe")
                topic_id = topic.topic_id
        saved = self.get_topic(topic_id)
        if saved is None:
            raise RuntimeError("No se pudo recuperar el tema guardado")
        return saved

    def reorder_topics(self, ordered_topic_ids: list[int]) -> None:
        with self.database.transaction(immediate=True) as connection:
            rows = connection.execute("SELECT topic_id FROM topics WHERE name <> '_inbox'").fetchall()
            current = {int(row["topic_id"]) for row in rows}
            if set(ordered_topic_ids) != current or len(ordered_topic_ids) != len(current):
                raise ValueError("El orden debe contener exactamente todos los temas salvo _inbox")
            connection.execute("UPDATE topics SET position = -topic_id WHERE name <> '_inbox'")
            for position, topic_id in enumerate(ordered_topic_ids):
                connection.execute(
                    "UPDATE topics SET position = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                    "WHERE topic_id = ?",
                    (position, topic_id),
                )

    def assign_capture(
        self,
        capture_id: str,
        *,
        topic_id: int,
        profile_id: int,
        source_origin: SourceOrigin,
        obsolescence_date: date | None,
    ) -> None:
        with self.database.transaction(immediate=True) as connection:
            cursor = connection.execute(
                "UPDATE captures SET topic_id = ?, profile_id = ?, source_origin = ?, "
                "obsolescence_date = ?, domain_enriched_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE capture_id = ? AND status = 'PENDING' AND domain_enriched_at IS NULL",
                (
                    topic_id,
                    profile_id,
                    source_origin.value,
                    obsolescence_date.isoformat() if obsolescence_date else None,
                    capture_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("La captura no está PENDING, no existe o ya fue enriquecida")
