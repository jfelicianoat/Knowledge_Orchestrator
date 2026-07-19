from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from importlib.resources import files
from pathlib import Path


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        if readonly:
            # Las conexiones de solo lectura (snapshots de UI, backup, diagnóstico) nunca
            # escriben, así que no necesitan el fsync de FULL; query_only evita además que
            # un bug las use accidentalmente para escribir.
            connection.execute("PRAGMA query_only = ON")
        else:
            connection.execute("PRAGMA synchronous = FULL")
        return connection

    @contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with closing(self.connect()) as connection:
            mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            if str(mode).lower() != "wal":
                raise RuntimeError(f"SQLite no pudo activar WAL: {mode}")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT "
                "(strftime('%Y-%m-%dT%H:%M:%fZ', 'now')))"
            )
            connection.commit()

        migration_root = files("knowledge_orchestrator").joinpath("migrations")
        migration_names = sorted(item.name for item in migration_root.iterdir() if item.name.endswith(".sql"))
        for name in migration_names:
            version = int(name.split("_", 1)[0])
            with closing(self.connect()) as connection:
                already_applied = connection.execute(
                    "SELECT 1 FROM schema_migrations WHERE version = ?", (version,)
                ).fetchone()
                if already_applied:
                    continue
                sql = migration_root.joinpath(name).read_text(encoding="utf-8")
                script = (
                    "BEGIN IMMEDIATE;\n"
                    f"{sql}\n"
                    f"INSERT INTO schema_migrations(version) VALUES ({version});\n"
                    "COMMIT;"
                )
                try:
                    connection.executescript(script)
                except BaseException:
                    connection.rollback()
                    raise

    def journal_mode(self) -> str:
        with closing(self.connect()) as connection:
            return str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
