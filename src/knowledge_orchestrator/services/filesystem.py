from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any


def write_synced(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


#: `ERROR_NOT_SAME_DEVICE` de Windows; en POSIX llega como `errno.EXDEV`.
_WINDOWS_NOT_SAME_DEVICE = 17


def _is_cross_device(error: OSError) -> bool:
    return error.errno == errno.EXDEV or getattr(error, "winerror", None) == _WINDOWS_NOT_SAME_DEVICE


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def move_file(source: Path, target: Path) -> None:
    """Mueve un fichero también entre unidades, sin dejar nunca un destino a medias.

    `os.replace` solo renombra dentro del mismo volumen. La configuración real
    del usuario tiene la carpeta vigilada en C: y los datos en Y: (Google
    Drive), y cada cuarentena fallaba con «no es el mismo dispositivo»: 35
    intenciones sin completar en su base. Entre volúmenes se copia a un
    temporal junto al destino, se sincroniza, se comprueba el hash y solo
    entonces se renombra y se retira el origen. Si algo falla antes del
    renombrado, el origen sigue intacto.
    """

    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(source, target)
        return
    except OSError as error:
        if not _is_cross_device(error):
            raise
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        with source.open("rb") as source_stream, temporary.open("wb") as target_stream:
            shutil.copyfileobj(source_stream, target_stream, 1024 * 1024)
            target_stream.flush()
            os.fsync(target_stream.fileno())
        if _sha256_of(temporary) != _sha256_of(source):
            raise OSError(f"La copia de {source.name} no coincide con el original")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    source.unlink(missing_ok=True)


def install_new_file(temporary: Path, destination: Path) -> None:
    """Instala `temporary` como `destination` solo si el destino no existe.

    Lo normal es un enlace duro: nunca sustituye un fichero que apareciera
    entre la comprobación y la escritura. Pero no todos los volúmenes los
    admiten —la bóveda real del usuario vive en Google Drive y `os.link`
    devuelve «Función incorrecta»—, y entonces ninguna nota llegaba a
    publicarse: tres quedaron para siempre en PUBLISHING. En Windows,
    `os.rename` tiene la misma garantía (falla con `FileExistsError` si el
    destino existe, y es atómico), así que es la alternativa segura. En otros
    sistemas `rename` sustituye sin avisar y se deja fallar.

    Lanza `FileExistsError` si el destino ya está ocupado.
    """

    try:
        os.link(temporary, destination)
    except FileExistsError:
        raise
    except OSError:
        if os.name != "nt":
            raise
        os.rename(temporary, destination)
        return
    temporary.unlink(missing_ok=True)


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
