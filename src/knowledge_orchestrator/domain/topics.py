from __future__ import annotations

import re
import unicodedata
from pathlib import PurePosixPath

from .models import TopicDefinition

INVALID_FOLDER_CHARACTERS = re.compile(r'[<>:"|?*]')
WINDOWS_RESERVED_NAMES = {
    "con", "prn", "aux", "nul",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


class TopicValidationError(ValueError):
    pass


def normalize_search_text(value: object) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or "").casefold())
    without_marks = "".join(character for character in decomposed if not unicodedata.combining(character))
    words = "".join(character if character.isalnum() else " " for character in without_marks)
    words = re.sub(r"\s+", " ", words).strip()
    return f" {words} " if words else " "


def validate_topic(topic: TopicDefinition) -> TopicDefinition:
    if not topic.name.strip() or len(topic.name) > 100:
        raise TopicValidationError("name debe contener entre 1 y 100 caracteres")
    if topic.position < 0:
        raise TopicValidationError("position debe ser mayor o igual que cero")
    if topic.default_profile_id < 1:
        raise TopicValidationError("default_profile_id debe identificar un perfil existente")
    if topic.obsolescence_days is not None and topic.obsolescence_days < 0:
        raise TopicValidationError("obsolescence_days debe ser null o mayor o igual que cero")
    folder = topic.folder.replace("\\", "/").strip("/")
    parsed = PurePosixPath(folder)
    if (
        not folder
        or folder == "."
        or parsed.is_absolute()
        or ".." in parsed.parts
        or INVALID_FOLDER_CHARACTERS.search(folder)
        or any(part.rstrip(". ") != part for part in parsed.parts)
        or any(part.casefold().split(".", 1)[0] in WINDOWS_RESERVED_NAMES for part in parsed.parts)
    ):
        raise TopicValidationError("folder debe ser una ruta relativa segura")
    normalized_keywords = tuple(
        keyword.strip() for keyword in topic.keywords if isinstance(keyword, str) and keyword.strip()
    )
    if topic.name != "_inbox" and not normalized_keywords:
        raise TopicValidationError("un tema clasificable necesita al menos una keyword")
    normalized_for_search = [normalize_search_text(keyword).strip() for keyword in normalized_keywords]
    if any(not keyword for keyword in normalized_for_search):
        raise TopicValidationError("keywords debe contener texto alfanumérico")
    if len(set(normalized_for_search)) != len(normalized_for_search):
        raise TopicValidationError("keywords contiene duplicados")
    return TopicDefinition(
        name=topic.name.strip(),
        folder=folder,
        keywords=normalized_keywords,
        position=topic.position,
        default_profile_id=topic.default_profile_id,
        is_updatable=topic.is_updatable,
        obsolescence_days=topic.obsolescence_days,
        auto_review=topic.auto_review,
        enabled=topic.enabled,
        topic_id=topic.topic_id,
    )
