from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any


def write_synced(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    try:
        write_synced(temporary, encoded)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def unique_destination(directory: Path, filename: str, discriminator: str | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    source = Path(filename)
    label = discriminator or uuid.uuid4().hex[:8]
    candidate = directory / f"{source.stem} [{label}]{source.suffix}"
    sequence = 2
    while candidate.exists():
        candidate = directory / f"{source.stem} [{label}-{sequence}]{source.suffix}"
        sequence += 1
    return candidate
