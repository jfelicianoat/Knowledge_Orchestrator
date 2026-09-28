from __future__ import annotations

import hashlib
import json
import logging
import logging.handlers
import platform
import sqlite3
import sys
import zipfile
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from knowledge_orchestrator.config import BrokerSettings, PipelinePaths
from knowledge_orchestrator.redaction import sanitize as sanitize
from knowledge_orchestrator.repositories.database import Database

LOG_FILE_NAME = "orchestrator.log"


class JsonFormatter(logging.Formatter):
    def __init__(self, *, known_secrets: tuple[str, ...] = ()) -> None:
        super().__init__()
        self._known_secrets = known_secrets

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(sanitize(payload, known_secrets=self._known_secrets), ensure_ascii=False, default=str)


@dataclass(frozen=True, slots=True)
class BackupResult:
    path: Path
    source: Path
    size_bytes: int
    created_at: str


@dataclass(frozen=True, slots=True)
class DiagnosticResult:
    path: Path
    created_at: str
    files: tuple[str, ...]


def configure_logging(
    paths: PipelinePaths, *, level: int = logging.INFO, known_secrets: tuple[str, ...] = ()
) -> Path:
    paths.logs.mkdir(parents=True, exist_ok=True)
    log_path = paths.logs / LOG_FILE_NAME
    root = logging.getLogger()
    root.setLevel(level)
    shutdown_logging()
    handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
        delay=True,
    )
    handler.setFormatter(JsonFormatter(known_secrets=known_secrets))
    handler._knowledge_orchestrator = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    return log_path


def shutdown_logging() -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_knowledge_orchestrator", False):
            root.removeHandler(handler)
            handler.close()


def backup_database(database: Database, paths: PipelinePaths, *, now: datetime | None = None) -> BackupResult:
    timestamp = _timestamp(now)
    paths.backups.mkdir(parents=True, exist_ok=True)
    target = paths.backups / f"orchestrator-{timestamp}.db"
    with closing(database.connect(readonly=True)) as source:
        with closing(sqlite3.connect(target)) as destination:
            source.backup(destination)
            destination.execute("PRAGMA wal_checkpoint(FULL)")
    size = target.stat().st_size
    return BackupResult(path=target, source=database.path, size_bytes=size, created_at=timestamp)


def export_diagnostics(
    database: Database,
    paths: PipelinePaths,
    broker_settings: BrokerSettings,
    *,
    output_path: Path | None = None,
    now: datetime | None = None,
) -> DiagnosticResult:
    timestamp = _timestamp(now)
    paths.diagnostics.mkdir(parents=True, exist_ok=True)
    target = output_path or paths.diagnostics / f"knowledge-orchestrator-diagnostics-{timestamp}.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "created_at": timestamp,
        "python": sys.version,
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "paths": _redact(asdict(paths)),
        "broker_settings": _redact(asdict(broker_settings)),
        "database": _database_summary(database),
        "directories": _directory_summary(paths),
    }
    log_text = _read_log_tail(paths.logs / LOG_FILE_NAME)
    known_secrets = (broker_settings.admin_token,) if broker_settings.admin_token else ()
    manifest = sanitize(manifest, known_secrets=known_secrets)
    # Parse each complete JSON record before sanitizing nested textual payloads.
    log_text = "\n".join(sanitize(line, known_secrets=known_secrets) for line in log_text.splitlines())
    with zipfile.ZipFile(target, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("diagnostics.json", json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
        archive.writestr("logs/orchestrator-tail.log", log_text)
        archive.writestr(
            "README.txt",
            "Incluye contadores, entorno, configuración y líneas completas de logs saneadas.\n"
            "No adjunta SQLite ni archivos de notas. Oculta campos de credenciales reconocidos y el token "
            "Broker configurado. Los mensajes libres antiguos pueden contener otros datos privados; "
            "revise el paquete antes de compartirlo.\n",
        )
    with zipfile.ZipFile(target) as archive:
        names = tuple(archive.namelist())
    return DiagnosticResult(path=target, created_at=timestamp, files=names)


def _redact(value: Any) -> Any:
    return sanitize(value)


def _database_summary(database: Database) -> dict[str, Any]:
    summary: dict[str, Any] = {"path_exists": database.path.exists()}
    if not database.path.exists():
        return summary
    with closing(database.connect(readonly=True)) as connection:
        summary["journal_mode"] = connection.execute("PRAGMA journal_mode").fetchone()[0]
        summary["user_version"] = connection.execute("PRAGMA user_version").fetchone()[0]
        summary["schema_version"] = connection.execute("PRAGMA schema_version").fetchone()[0]
        for table in ("captures", "tasks", "workflows", "notes", "update_candidates", "semantic_jobs", "events"):
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            if exists:
                summary[f"{table}_count"] = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    return summary


def _directory_summary(paths: PipelinePaths) -> dict[str, dict[str, int | bool]]:
    result: dict[str, dict[str, int | bool]] = {}
    for name in ("inbox", "staging", "processing", "completed", "failed", "rejected", "state", "logs", "backups"):
        directory = getattr(paths, name)
        result[name] = {
            "exists": directory.exists(),
            "files": sum(1 for item in directory.rglob("*") if item.is_file()) if directory.exists() else 0,
        }
    return result


def _read_log_tail(path: Path, *, max_bytes: int = 200_000) -> str:
    if max_bytes < 1:
        raise ValueError("max_bytes debe ser positivo")
    if not path.exists():
        return ""
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > max_bytes:
            handle.seek(size - max_bytes - 1)
            previous = handle.read(1)
        else:
            previous = b"\n"
        data = handle.read(max_bytes)
    if previous != b"\n":
        # The cut may be inside a secret, with its identifying key outside the tail.
        newline = data.find(b"\n")
        data = data[newline + 1:] if newline >= 0 else b""
    # A concurrent writer may not have finished the last record yet.
    if data and not data.endswith(b"\n"):
        data = data[:data.rfind(b"\n") + 1]
    return data.decode("utf-8", errors="replace")


def _timestamp(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------- copia integral
#
# `backup_database` copia solo SQLite, y el estado del producto vive en varios
# soportes: la base, las fuentes archivadas (sin ellas no se puede reprocesar),
# lo rechazado, lo que está a medio procesar y las notas de la bóveda. La copia
# integral guarda los cuatro primeros con un manifiesto de hashes y deja la
# bóveda como referencia (ruta + hash): la bóveda la sincroniza Obsidian y
# copiarla entera duplicaría el conocimiento del usuario en cada copia.

FULL_BACKUP_FORMAT = "knowledge-orchestrator-full-backup/1"
#: Carpetas de la raíz de datos que forman parte de la copia.
FULL_BACKUP_FOLDERS = ("completed", "rejected", "processing")
_DATABASE_MEMBER = "state/orchestrator.db"
#: Columnas de ruta que apuntan fuera de la raíz de datos y no se reescriben.
_EXTERNAL_PATH_COLUMNS = frozenset({"vault_path"})


class RestoreError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FullBackupResult:
    path: Path
    created_at: str
    files: int
    vault_notes: int


@dataclass(frozen=True, slots=True)
class RestoreResult:
    root: Path
    files: int
    rewritten_paths: int


def _data_root(paths: PipelinePaths) -> Path:
    return paths.state.parent


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _vault_references(database_path: Path) -> list[dict[str, Any]]:
    with closing(sqlite3.connect(database_path)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT note_id, capture_id, revision, status, vault_path, content_hash FROM notes ORDER BY note_id"
        ).fetchall()
    references = []
    for row in rows:
        path = Path(row["vault_path"]) if row["vault_path"] else None
        present = path is not None and path.is_file()
        references.append({
            "note_id": row["note_id"], "capture_id": row["capture_id"], "revision": row["revision"],
            "status": row["status"], "vault_path": row["vault_path"], "recorded_hash": row["content_hash"],
            "present": present, "current_hash": _sha256_file(path) if present and path is not None else None,
        })
    return references


def create_full_backup(
    database: Database, paths: PipelinePaths, *, output_path: Path | None = None, now: datetime | None = None,
) -> FullBackupResult:
    """ZIP restaurable: SQLite consistente, fuentes y manifiesto con hashes. Sin credenciales."""

    from knowledge_orchestrator import __version__

    timestamp = _timestamp(now)
    root = _data_root(paths)
    paths.backups.mkdir(parents=True, exist_ok=True)
    target = output_path or paths.backups / f"knowledge-orchestrator-full-{timestamp}.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    snapshot = backup_database(database, paths, now=now).path
    try:
        members: dict[str, Path] = {_DATABASE_MEMBER: snapshot}
        for folder in FULL_BACKUP_FOLDERS:
            directory = getattr(paths, folder)
            if not directory.exists():
                continue
            for item in sorted(directory.rglob("*")):
                if item.is_file():
                    members[f"{folder}/{item.relative_to(directory).as_posix()}"] = item
        files = {name: {"sha256": _sha256_file(path), "size": path.stat().st_size} for name, path in members.items()}
        vault = _vault_references(snapshot)
        manifest = {
            "format": FULL_BACKUP_FORMAT,
            "app_version": __version__,
            "created_at": timestamp,
            "data_root": str(root),
            "paths": {"inbox": str(paths.inbox), "obsidian_vault": str(paths.obsidian_vault)},
            "files": files,
            "vault_notes": vault,
            "credentials": "No incluidas. Tras restaurar, vuelva a configurar el token del Broker y la "
                           "conexión con Obsidian en Ajustes: se guardan cifradas para este usuario de Windows.",
        }
        temporary = target.with_name(f".{target.name}.tmp")
        with zipfile.ZipFile(temporary, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, path in members.items():
                archive.write(path, name)
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        temporary.replace(target)
    finally:
        snapshot.unlink(missing_ok=True)
    return FullBackupResult(path=target, created_at=timestamp, files=len(files), vault_notes=len(vault))


def _safe_member(name: str) -> PurePosixPath:
    member = PurePosixPath(name)
    if member.is_absolute() or ".." in member.parts or ":" in name or "\\" in name:
        raise RestoreError(f"Ruta no permitida en la copia: {name}")
    return member


def restore_full_backup(archive_path: Path, root: Path) -> RestoreResult:
    """Restaura en una raíz vacía; verifica cada hash antes de escribir nada."""

    root = Path(root)
    if root.exists() and any(root.iterdir()):
        raise RestoreError("La carpeta de destino no está vacía; la restauración no sobrescribe datos.")
    try:
        archive = zipfile.ZipFile(archive_path)
    except (OSError, zipfile.BadZipFile) as error:
        raise RestoreError(f"No es una copia legible: {error}") from error
    with archive:
        try:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        except (KeyError, ValueError) as error:
            raise RestoreError("La copia no tiene un manifiesto válido") from error
        if manifest.get("format") != FULL_BACKUP_FORMAT or not isinstance(manifest.get("files"), dict):
            raise RestoreError("Formato de copia no reconocido")
        expected: dict[str, Any] = manifest["files"]
        present = {name for name in archive.namelist() if name != "manifest.json" and not name.endswith("/")}
        if present != set(expected):
            raise RestoreError("El contenido de la copia no coincide con su manifiesto")
        if _DATABASE_MEMBER not in expected:
            raise RestoreError("La copia no contiene la base de datos")
        # Primera pasada: solo verificar. Nada se escribe si un solo hash falla.
        for name, entry in expected.items():
            _safe_member(name)
            if not isinstance(entry, dict) or hashlib.sha256(archive.read(name)).hexdigest() != entry.get("sha256"):
                raise RestoreError(f"Hash distinto en {name}: la copia está dañada o fue modificada")
        root.mkdir(parents=True, exist_ok=True)
        for name in expected:
            destination = root.joinpath(*_safe_member(name).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(name))
    for name, entry in expected.items():
        if _sha256_file(root.joinpath(*PurePosixPath(name).parts)) != entry["sha256"]:
            raise RestoreError(f"Hash distinto tras escribir {name}")
    database_path = root.joinpath(*PurePosixPath(_DATABASE_MEMBER).parts)
    old_root = str(manifest.get("data_root") or "")
    rewritten = _rewrite_data_root(database_path, Path(old_root), root) if old_root else 0
    for folder in ("inbox", "staging", "failed", "logs", "backups", "diagnostics"):
        (root / folder).mkdir(exist_ok=True)
    return RestoreResult(root=root, files=len(expected), rewritten_paths=rewritten)


def _rewrite_data_root(database_path: Path, old_root: Path, new_root: Path) -> int:
    """Las rutas de la raíz antigua pasan a la nueva; las de la bóveda no se tocan."""

    changed = 0
    with closing(sqlite3.connect(database_path)) as connection:
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )]
        for table in tables:
            columns = [
                row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')
                if str(row[1]).endswith("path") and row[1] not in _EXTERNAL_PATH_COLUMNS
            ]
            for column in columns:
                rows = connection.execute(
                    f'SELECT rowid, "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL'
                ).fetchall()
                for rowid, value in rows:
                    try:
                        relative = Path(str(value)).relative_to(old_root)
                    except ValueError:
                        continue
                    connection.execute(
                        f'UPDATE "{table}" SET "{column}" = ? WHERE rowid = ?', (str(new_root / relative), rowid)
                    )
                    changed += 1
        connection.commit()
    return changed
