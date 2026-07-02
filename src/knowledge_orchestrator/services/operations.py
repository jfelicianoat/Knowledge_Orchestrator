from __future__ import annotations

import json
import logging
import logging.handlers
import platform
import re
import sqlite3
import sys
import zipfile
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from knowledge_orchestrator.config import BrokerSettings, PipelinePaths
from knowledge_orchestrator.repositories.database import Database


LOG_FILE_NAME = "orchestrator.log"
SENSITIVE_KEYS = re.compile(r"(token|secret|password|api[_-]?key|authorization|cookie)", re.IGNORECASE)
URL_CREDENTIALS = re.compile(r"://([^:/@\s]+):([^@\s]+)@")
SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b(token|secret|password|api[_-]?key|authorization|cookie)\b\s*[:=]\s*([^\s,;]+)"
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": sanitize(record.getMessage()),
        }
        if record.exc_info:
            payload["exception"] = sanitize(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


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


def configure_logging(paths: PipelinePaths, *, level: int = logging.INFO) -> Path:
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
    handler.setFormatter(JsonFormatter())
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
    with zipfile.ZipFile(target, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("diagnostics.json", json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
        archive.writestr("logs/orchestrator-tail.log", sanitize(log_text))
        archive.writestr("README.txt", "Paquete diagnóstico sin secretos. No incluye base SQLite ni contenido de notas.\n")
    with zipfile.ZipFile(target) as archive:
        names = tuple(archive.namelist())
    return DiagnosticResult(path=target, created_at=timestamp, files=names)


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "***REDACTED***" if SENSITIVE_KEYS.search(str(key)) else sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize(item) for item in value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str):
        redacted = URL_CREDENTIALS.sub("://***:***@", value)
        return SENSITIVE_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=***REDACTED***", redacted)
    return value


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
    if not path.exists():
        return ""
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > max_bytes:
            handle.seek(size - max_bytes)
        data = handle.read()
    return data.decode("utf-8", errors="replace")


def _timestamp(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
