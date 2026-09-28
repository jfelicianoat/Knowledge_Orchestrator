"""Importar documentos desde el escritorio sin exigir el contrato del plugin.

«Importar documentos» copiaba el fichero tal cual al inbox, y la ingesta solo
acepta capturas con frontmatter contractual y sección `## Transcripción`. Un
Markdown normal —unos apuntes, un artículo guardado— acababa en cuarentena
con un error de contrato que la persona no tenía por qué entender.

Aquí se clasifica cada fichero antes de copiarlo:

- `compatible`: ya es una captura válida; se copia igual que antes.
- `malformed`: parece una captura (declara `contract_version` o `capture_id`)
  pero no valida; se explica el motivo y no se copia.
- `ordinary`: texto normal; se puede convertir en una captura nueva.

La conversión nunca toca el original: escribe un fichero nuevo en el inbox.
"""
from __future__ import annotations

import hashlib
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from knowledge_orchestrator.domain.contracts import MAX_CAPTURE_BYTES, TRANSCRIPT_HEADING, parse_capture_bytes
from knowledge_orchestrator.domain.errors import CaptureContractError

from .filesystem import write_synced

IMPORTABLE_SUFFIXES = (".md", ".markdown", ".txt")
#: Claves que delatan que el autor quería escribir una captura contractual.
_CONTRACT_MARKERS = ("contract_version", "capture_id")
_HEADING = re.compile(r"(?m)^#{1,6}[ \t]+(.+?)[ \t#]*$")


@dataclass(frozen=True, slots=True)
class ImportCandidate:
    path: Path
    kind: str  # compatible | malformed | ordinary | unreadable
    title: str
    size_bytes: int
    reason: str = ""


def _split_frontmatter(text: str) -> tuple[dict | None, str]:
    """Frontmatter YAML (si lo hay y es un objeto) y el cuerpo restante."""

    if not text.startswith("---\n"):
        return None, text
    closing = text.find("\n---\n", 4)
    if closing < 0:
        return None, text
    try:
        metadata = yaml.safe_load(text[4:closing])
    except yaml.YAMLError:
        return None, text
    if not isinstance(metadata, dict):
        return None, text
    return metadata, text[closing + 5:]


def _readable_reason(error: CaptureContractError) -> str:
    issue = error.issue
    field = "el documento" if issue.field == "$" else f"«{issue.field}»"
    return f"{field}: {issue.reason}"


def inspect_import(path: Path) -> ImportCandidate:
    """Decide qué hacer con un fichero elegido por la persona, sin modificarlo."""

    source = Path(path)
    fallback_title = source.stem.strip() or "Documento importado"
    try:
        raw = source.read_bytes()
    except OSError as error:
        return ImportCandidate(source, "unreadable", fallback_title, 0, f"No se pudo leer: {error.strerror or error}")
    size = len(raw)
    if source.suffix.lower() not in IMPORTABLE_SUFFIXES:
        return ImportCandidate(source, "unreadable", fallback_title, size, "Solo se admiten .md y .txt")
    if size > MAX_CAPTURE_BYTES:
        return ImportCandidate(source, "unreadable", fallback_title, size, "El fichero supera 20 MiB")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return ImportCandidate(source, "unreadable", fallback_title, size, "El fichero no está en UTF-8")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    metadata, body = _split_frontmatter(normalized)
    if metadata is not None and any(marker in metadata for marker in _CONTRACT_MARKERS):
        try:
            document = parse_capture_bytes(raw)
        except CaptureContractError as error:
            title = str(metadata.get("title") or fallback_title)
            return ImportCandidate(source, "malformed", title, size, _readable_reason(error))
        return ImportCandidate(source, "compatible", document.title, size)
    if not body.strip():
        return ImportCandidate(source, "unreadable", fallback_title, size, "El documento está vacío")
    return ImportCandidate(source, "ordinary", detect_title(body, metadata, fallback_title), size)


def detect_title(body: str, metadata: dict | None, fallback: str) -> str:
    declared = (metadata or {}).get("title")
    if isinstance(declared, str) and declared.strip():
        return declared.strip()[:500]
    heading = _HEADING.search(body)
    if heading and heading.group(1).strip():
        return heading.group(1).strip()[:500]
    return fallback[:500]


def build_capture(path: Path, *, now: datetime | None = None) -> tuple[str, str]:
    """Envuelve un documento normal en una captura válida. Devuelve (capture_id, markdown).

    El `capture_id` sale del contenido: importar dos veces el mismo texto da la
    misma captura y la ingesta la reconoce como duplicada en vez de procesarla
    dos veces.
    """

    source = Path(path)
    raw = source.read_bytes()
    text = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    metadata, body = _split_frontmatter(text)
    title = detect_title(body, metadata, source.stem.strip() or "Documento importado")
    content = body.strip("\n")
    if not content.strip():
        raise ValueError("El documento está vacío")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    capture_id = f"manual_{digest[:40]}"
    captured_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    envelope = {
        "contract_version": "1.0",
        "capture_id": capture_id,
        "source_type": "document",
        "title": title,
        "captured_at": captured_at,
        "has_transcript": True,
        "status": "pending",
        "imported_from": source.name,
    }
    # La sección empieza en el primer encabezado: todo lo que sigue, incluido
    # otro «## Transcripción» del propio texto, es contenido y llega intacto.
    markdown = (
        "---\n" + yaml.safe_dump(envelope, allow_unicode=True, sort_keys=False) + "---\n\n"
        + f"{TRANSCRIPT_HEADING}\n\n" + content + "\n"
    )
    parse_capture_bytes(markdown.encode("utf-8"))  # la envoltura tiene que validar ya aquí
    return capture_id, markdown


def write_converted(path: Path, inbox: Path) -> Path:
    """Escribe la captura convertida en el inbox, de forma atómica. El original no se toca."""

    capture_id, markdown = build_capture(path)
    inbox.mkdir(parents=True, exist_ok=True)
    target = inbox / f"{capture_id}.md"
    encoded = markdown.encode("utf-8")
    if target.exists():
        return target  # misma captura ya entregada: la ingesta decide si es duplicada
    temporary = inbox / f".{capture_id}.{uuid.uuid4().hex}.tmp"
    try:
        write_synced(temporary, encoded)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target
