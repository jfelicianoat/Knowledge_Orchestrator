from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_orchestrator.services.path_settings import PipelinePathStore, load_pipeline_paths


class PipelinePathSettingsTests(unittest.TestCase):
    def test_saves_and_loads_the_three_user_facing_locations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            store = PipelinePathStore(base / "settings" / "paths.json")
            saved = store.save(
                data_root=base / "datos",
                inbox=base / "entrada",
                obsidian_vault=base / "resultados",
            )

            loaded = load_pipeline_paths(config_path=store.path, home=base / "usuario")

            self.assertEqual(loaded, saved)
            self.assertEqual(loaded.processing, base / "datos" / "processing")
            self.assertTrue(store.path.exists())

    def test_environment_variables_take_precedence_over_saved_locations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            store = PipelinePathStore(base / "paths.json")
            store.save(base / "datos", base / "entrada", base / "resultados")
            environment = {
                "KO_ROOT": str(base / "entorno-datos"),
                "KO_INBOX_DIR": str(base / "entorno-entrada"),
                "KO_OBSIDIAN_VAULT": str(base / "entorno-resultados"),
            }

            with patch.dict("os.environ", environment, clear=False):
                loaded = load_pipeline_paths(config_path=store.path, home=base / "usuario")

            self.assertEqual(loaded.state, base / "entorno-datos" / "state")
            self.assertEqual(loaded.inbox, base / "entorno-entrada")
            self.assertEqual(loaded.obsidian_vault, base / "entorno-resultados")


if __name__ == "__main__":
    unittest.main()
