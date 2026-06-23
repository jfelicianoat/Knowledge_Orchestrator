from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urlparse

import yaml

from .errors import CaptureContractError, ContractIssue
from .models import CaptureDocument

MAX_CAPTURE_BYTES = 20 * 1024 * 1024
CAPTURE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TRANSCRIPT_HEADING = "## Transcripción"


class _UniqueKeySafeLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"duplicate key: {key}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _raise(field: str, reason: str, version: str | None = None) -> None:
    raise CaptureContractError(
        ContractIssue(
            boundary="plugin_to_orchestrator",
            field=field,
            reason=reason,
            contract_version=version,
        )
    )


def _require_type(metadata: dict[str, Any], field: str, expected: type, version: str) -> Any:
    if field not in metadata:
        _raise(field, "campo obligatorio ausente", version)
    value = metadata[field]
    if expected is int and (not isinstance(value, int) or isinstance(value, bool)):
        _raise(field, "debe ser integer", version)
    if expected is not int and not isinstance(value, expected):
        _raise(field, f"debe ser {expected.__name__}", version)
    return value


def _optional_string(metadata: dict[str, Any], field: str, version: str) -> None:
    value = metadata.get(field)
    if value is not None and not isinstance(value, str):
        _raise(field, "debe ser string o null", version)


def _valid_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _validate_datetime(value: str, field: str, version: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _raise(field, "debe usar ISO 8601", version)
    if parsed.tzinfo is None:
        _raise(field, "debe incluir zona horaria", version)


def _validate_metadata(metadata: dict[str, Any], transcript: str) -> None:
    raw_version = metadata.get("contract_version")
    if not isinstance(raw_version, str):
        _raise("contract_version", "campo obligatorio string ausente", None)
    version = raw_version
    if version != "1.0":
        _raise("contract_version", "versión soportada: 1.0", version)

    capture_id = _require_type(metadata, "capture_id", str, version)
    if not CAPTURE_ID_PATTERN.fullmatch(capture_id):
        _raise("capture_id", "solo admite A-Z, a-z, 0-9, punto, guion y guion bajo; máximo 128", version)

    source_type = _require_type(metadata, "source_type", str, version)
    title = _require_type(metadata, "title", str, version)
    if not title.strip() or len(title) > 500:
        _raise("title", "debe contener entre 1 y 500 caracteres", version)

    captured_at = _require_type(metadata, "captured_at", str, version)
    _validate_datetime(captured_at, "captured_at", version)
    has_transcript = _require_type(metadata, "has_transcript", bool, version)
    status = _require_type(metadata, "status", str, version)
    if status != "pending":
        _raise("status", "debe ser pending", version)

    _optional_string(metadata, "source_url", version)
    if metadata.get("source_url") is not None and not _valid_http_url(metadata["source_url"]):
        _raise("source_url", "debe ser una URL HTTP(S) válida", version)
    _optional_string(metadata, "published_date", version)
    if metadata.get("published_date") is not None:
        published_date = metadata["published_date"]
        if not DATE_PATTERN.fullmatch(published_date):
            _raise("published_date", "debe usar YYYY-MM-DD", version)
        try:
            date.fromisoformat(published_date)
        except ValueError:
            _raise("published_date", "no es una fecha válida", version)
    _optional_string(metadata, "transcript_language", version)

    if has_transcript and not transcript.strip():
        _raise("transcript_content", "es obligatorio cuando has_transcript es true", version)
    if not has_transcript and transcript.strip():
        _raise("transcript_content", "debe estar vacío cuando has_transcript es false", version)

    if source_type == "youtube":
        required_types = {
            "source_url": str,
            "video_id": str,
            "channel": str,
            "duration_seconds": int,
            "extraction_method": str,
            "plugin_version": str,
        }
        for field, expected in required_types.items():
            _require_type(metadata, field, expected, version)
        if not metadata["video_id"] or len(metadata["video_id"]) > 32:
            _raise("video_id", "debe contener entre 1 y 32 caracteres", version)
        if not metadata["channel"].strip() or len(metadata["channel"]) > 300:
            _raise("channel", "debe contener entre 1 y 300 caracteres", version)
        if metadata["duration_seconds"] < 0:
            _raise("duration_seconds", "debe ser mayor o igual que cero", version)
        if metadata["extraction_method"] not in {"schema_jsonld", "yt_globals", "dom_selectors"}:
            _raise("extraction_method", "valor no permitido", version)
        transcript_source = metadata.get("transcript_source")
        if transcript_source not in {"manual", "automatic", None}:
            _raise("transcript_source", "debe ser manual, automatic o null", version)
        if has_transcript and transcript_source is None:
            _raise("transcript_source", "es obligatorio cuando existe transcripción", version)
        if not has_transcript and transcript_source is not None:
            _raise("transcript_source", "debe ser null cuando no existe transcripción", version)
        if not _valid_http_url(metadata["source_url"]):
            _raise("source_url", "debe ser una URL HTTP(S) válida", version)
        if not re.fullmatch(r"\d+\.\d+\.\d+", metadata["plugin_version"]):
            _raise("plugin_version", "debe usar versión semántica X.Y.Z", version)
        _optional_string(metadata, "channel_url", version)
        if metadata.get("channel_url") is not None and not _valid_http_url(metadata["channel_url"]):
            _raise("channel_url", "debe ser una URL HTTP(S) válida", version)


def parse_capture_bytes(content: bytes) -> CaptureDocument:
    if len(content) > MAX_CAPTURE_BYTES:
        _raise("$", "el fichero supera 20 MiB", None)
    try:
        markdown = content.decode("utf-8")
    except UnicodeDecodeError:
        _raise("$", "el fichero debe usar UTF-8", None)
    normalized = markdown.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.startswith("---\n"):
        _raise("$", "falta la apertura del frontmatter YAML", None)
    closing = normalized.find("\n---\n", 4)
    if closing < 0:
        _raise("$", "falta el cierre del frontmatter YAML", None)

    yaml_text = normalized[4:closing]
    try:
        metadata = yaml.load(yaml_text, Loader=_UniqueKeySafeLoader)
    except (yaml.YAMLError, TypeError) as error:
        _raise("$", f"YAML inválido: {error}", None)
    if not isinstance(metadata, dict):
        _raise("$", "el frontmatter debe ser un objeto", None)
    if not all(isinstance(key, str) for key in metadata):
        _raise("$", "todas las claves YAML deben ser strings", str(metadata.get("contract_version")) if metadata else None)

    body = normalized[closing + 5 :]
    heading_match = re.search(rf"(?m)^{re.escape(TRANSCRIPT_HEADING)}[ \t]*$", body)
    if heading_match is None:
        _raise("transcript_content", "falta la sección ## Transcripción", str(metadata.get("contract_version")))
    after_heading = body[heading_match.end() :]
    transcript = after_heading.lstrip("\n").rstrip("\n")
    _validate_metadata(metadata, transcript)
    return CaptureDocument(metadata=metadata, transcript_content=transcript, raw_markdown=normalized)
