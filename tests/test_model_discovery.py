from __future__ import annotations

import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from knowledge_orchestrator.config import PipelinePaths
from knowledge_orchestrator.runtime import build_runtime
from knowledge_orchestrator.services.model_discovery import ModelDiscoveryService


class FakeModelBroker:
    async def list_models(self) -> list[dict]:
        return [{
            "name": "llama3.1:8b",
            "provider": "ollama",
            "status": "available",
            "context_window": 8192,
        }]


class ModelDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_persists_discovered_model_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime = build_runtime(PipelinePaths.under(Path(temporary)))
            count = await ModelDiscoveryService(runtime.workflow_repository, FakeModelBroker()).refresh()
            self.assertEqual(count, 1)
            with closing(runtime.database.connect()) as connection:
                row = connection.execute("SELECT * FROM model_catalog").fetchone()
                self.assertEqual(row["name"], "llama3.1:8b")
                self.assertEqual(row["provider"], "ollama")
                self.assertEqual(row["context_window"], 8192)


if __name__ == "__main__":
    unittest.main()
