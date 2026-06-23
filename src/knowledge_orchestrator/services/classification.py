from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Mapping

from knowledge_orchestrator.domain.models import TopicDefinition
from knowledge_orchestrator.domain.topics import normalize_search_text


class TopicClassifier:
    def classify(
        self,
        metadata: Mapping[str, Any],
        topics: list[TopicDefinition],
        inbox_topic: TopicDefinition,
    ) -> TopicDefinition:
        searchable_values: list[object] = [
            metadata.get("title", ""),
            metadata.get("channel", ""),
            metadata.get("source_type", ""),
        ]
        for field in ("tags", "keywords"):
            value = metadata.get(field)
            if isinstance(value, list):
                searchable_values.extend(value)
            elif isinstance(value, str):
                searchable_values.append(value)
        haystack = normalize_search_text(" ".join(str(value) for value in searchable_values))

        for topic in sorted(topics, key=lambda item: (item.position, item.topic_id or 0)):
            if not topic.enabled or topic.name == "_inbox":
                continue
            if any(normalize_search_text(keyword) in haystack for keyword in topic.keywords):
                return topic
        return inbox_topic


def calculate_obsolescence_date(captured_at: str, topic: TopicDefinition) -> date | None:
    if not topic.is_updatable or topic.obsolescence_days is None:
        return None
    captured = datetime.fromisoformat(captured_at.replace("Z", "+00:00")).date()
    return captured + timedelta(days=topic.obsolescence_days)


def is_obsolete(obsolescence_date: date | None, *, today: date | None = None) -> bool:
    return obsolescence_date is not None and obsolescence_date <= (today or date.today())
