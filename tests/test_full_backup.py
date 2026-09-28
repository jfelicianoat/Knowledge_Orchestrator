"""Copia integral restaurable: base, fuentes y manifiesto con hashes."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path

from knowledge_orchestrator.config import BrokerSettings, PipelinePaths
from knowledge_orchestrator.repositories.database import Database
from knowledge_orchestrator.runtime import build_runtime
from knowledge_orchestrator.services.operations import (
    FULL_BACKUP_FORMAT,
    RestoreError,
    create_full_backup,
    restore_full_backup,
)
from tests.test_markdown_import import CAPTURE


class FullBackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.runtime = build_runtime(
            PipelinePaths.under(self.root / "datos"), broker_settings=BrokerSettings(base_url="http://127.0.0.1:9"),
        )
        paths = self.runtime.paths
        # Una captura archivada con su nota publicada en la bóveda.
        self.archived = paths.completed / "captura-r1-fuente.md"
        self.archived.write_text(CAPTURE, encoding="utf-8")
        self.note = paths.obsidian_vault / "General" / "Nota.md"
        self.note.parent.mkdir(parents=True, exist_ok=True)
        self.note.write_text("# Nota\n", encoding="utf-8")
        note_hash = hashlib.sha256(self.note.read_bytes()).hexdigest()
        with self.runtime.database.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT INTO captures(capture_id, contract_version, source_type, title, status, sha256, "
                "original_filename, metadata_json, transcript_content, archive_path) "
                "VALUES ('cap1', '1.0', 'document', 'Captura', 'COMPLETED', 'x', 'fuente.md', '{}', 'texto', ?)",
                (str(self.archived),),
            )
            connection.execute(
                "INSERT INTO notes(capture_id, revision, vault_path, status, content_hash, source_archive_path) "
                "VALUES ('cap1', 1, ?, 'PUBLISHED', ?, ?)",
                (str(self.note), note_hash, str(self.archived)),
            )

    def _backup(self) -> Path:
        return create_full_backup(self.runtime.database, self.runtime.paths, output_path=self.root / "copia.zip").path

    def test_backup_restores_into_empty_root_with_verified_hashes(self) -> None:
        archive = self._backup()
        with zipfile.ZipFile(archive) as bundle:
            manifest = json.loads(bundle.read("manifest.json"))
            self.assertIn("completed/captura-r1-fuente.md", bundle.namelist())
            self.assertFalse(any(name.startswith("vault") for name in bundle.namelist()))
        self.assertEqual(manifest["format"], FULL_BACKUP_FORMAT)
        self.assertEqual(manifest["vault_notes"][0]["vault_path"], str(self.note))
        self.assertTrue(manifest["vault_notes"][0]["present"])
        self.assertIn("token", manifest["credentials"])
        self.assertNotIn("admin_token", json.dumps(manifest))

        target = self.root / "restaurado"
        result = restore_full_backup(archive, target)

        self.assertEqual(result.files, len(manifest["files"]))
        self.assertEqual((target / "completed" / "captura-r1-fuente.md").read_text(encoding="utf-8"), CAPTURE)
        database = Database(target / "state" / "orchestrator.db")
        database.initialize()  # se abre y migra como cualquier base de la aplicación
        with closing(sqlite3.connect(database.path)) as connection:
            vault_path, archive_path = connection.execute(
                "SELECT vault_path, source_archive_path FROM notes WHERE capture_id = 'cap1'"
            ).fetchone()
            capture_archive = connection.execute(
                "SELECT archive_path FROM captures WHERE capture_id = 'cap1'"
            ).fetchone()[0]
        # Lo de la raíz de datos apunta a la nueva raíz; la bóveda sigue siendo la referencia original.
        self.assertEqual(vault_path, str(self.note))
        self.assertEqual(Path(archive_path), target / "completed" / "captura-r1-fuente.md")
        self.assertEqual(Path(capture_archive), target / "completed" / "captura-r1-fuente.md")
        self.assertTrue(Path(archive_path).exists())

    def test_restore_refuses_non_empty_root(self) -> None:
        archive = self._backup()
        target = self.root / "ocupado"
        target.mkdir()
        (target / "algo.txt").write_text("no tocar", encoding="utf-8")
        with self.assertRaises(RestoreError):
            restore_full_backup(archive, target)
        self.assertEqual((target / "algo.txt").read_text(encoding="utf-8"), "no tocar")

    def test_tampered_backup_is_refused_before_writing(self) -> None:
        archive = self._backup()
        tampered = self.root / "manipulada.zip"
        with zipfile.ZipFile(archive) as source, zipfile.ZipFile(tampered, "w") as target:
            for name in source.namelist():
                data = source.read(name)
                if name == "completed/captura-r1-fuente.md":
                    data = data.replace(b"Contenido", b"Otro contenido")
                target.writestr(name, data)
        destination = self.root / "destino"
        with self.assertRaises(RestoreError):
            restore_full_backup(tampered, destination)
        self.assertFalse(destination.exists() and any(destination.iterdir()))

    def test_unlisted_member_is_refused(self) -> None:
        archive = self._backup()
        with zipfile.ZipFile(archive, "a") as bundle:
            bundle.writestr("completed/intruso.md", "x")
        with self.assertRaises(RestoreError):
            restore_full_backup(archive, self.root / "destino")


if __name__ == "__main__":
    unittest.main()
