"""Copia integral periódica a otra carpeta (uso real 19-oct: base local, copia en Google Drive)."""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from knowledge_orchestrator.config import BrokerSettings, PipelinePaths
from knowledge_orchestrator.runtime import build_runtime
from knowledge_orchestrator.services.operations import restore_full_backup
from knowledge_orchestrator.services.path_settings import PipelinePathStore
from knowledge_orchestrator.worker.backup_worker import PREFIX, BackupWorker


class PeriodicBackupTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.target = self.root / "nube"
        self.runtime = build_runtime(
            PipelinePaths.under(self.root / "datos"), broker_settings=BrokerSettings(base_url="http://127.0.0.1:9"),
            backup_dir=self.target,
        )

    def test_backup_is_restorable_and_only_the_newest_ones_are_kept(self) -> None:
        worker = self.runtime.backup_worker
        assert worker is not None
        worker.keep = 2
        self.target.mkdir()
        # Tres copias anteriores: tras la nueva solo deben quedar las dos más recientes.
        for stamp in ("20260101T000000Z", "20260102T000000Z", "20260103T000000Z"):
            (self.target / f"{PREFIX}{stamp}.zip").write_bytes(b"vieja")
        (self.target / "otra-cosa.zip").write_bytes(b"no se toca")

        created = worker.run_once()

        self.assertEqual([path.name for path in worker.backups()],
                         [f"{PREFIX}20260103T000000Z.zip", created.name])
        self.assertTrue((self.target / "otra-cosa.zip").exists())
        restored = restore_full_backup(created, self.root / "restaurada")
        self.assertTrue((restored.root / "state" / "orchestrator.db").exists())

    def test_backup_is_due_only_after_the_interval(self) -> None:
        worker = BackupWorker(self.runtime.database, self.runtime.paths, self.target, interval_seconds=3600)
        self.assertTrue(worker.due(), "sin copias, la primera se hace enseguida")
        latest = worker.run_once()
        self.assertFalse(worker.due())
        old = time.time() - 7200
        os.utime(latest, (old, old))
        self.assertTrue(worker.due())

    def test_runtime_without_backup_dir_has_no_worker(self) -> None:
        runtime = build_runtime(
            PipelinePaths.under(self.root / "otra"), broker_settings=BrokerSettings(base_url="http://127.0.0.1:9"),
        )
        self.assertIsNone(runtime.backup_worker)


class BackupDirSettingTests(unittest.TestCase):
    def test_saving_locations_from_settings_keeps_backup_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            store = PipelinePathStore(base / "paths.json")
            store.path.write_text(json.dumps({"backup_dir": str(base / "nube")}), encoding="utf-8")

            store.save(data_root=base / "datos", inbox=base / "entrada", obsidian_vault=base / "boveda")

            self.assertEqual(store.backup_dir(), base / "nube")
            self.assertEqual(store.load()["data_root"], (base / "datos").resolve())


if __name__ == "__main__":
    unittest.main()
