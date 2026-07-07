from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_orchestrator.config import (
    ENV_BROKER_ADMIN_TOKEN,
    ENV_BROKER_URL,
    ENV_INBOX,
    ENV_OBSIDIAN_VAULT,
    ENV_ROOT,
    BrokerSettings,
    PipelinePaths,
)


class PipelinePathsEnvironmentOverrideTests(unittest.TestCase):
    def test_defaults_without_environment_overrides_use_hardcoded_paths(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            paths = PipelinePaths.defaults(home=Path("C:/Users/example"))

        self.assertEqual(paths.staging, Path("C:/YT-Pipeline/staging"))
        self.assertEqual(paths.inbox, Path("C:/Users/example/Downloads/YT-Knowledge-Inbox"))
        self.assertEqual(paths.obsidian_vault, Path("C:/ObsidianVault/Knowledge"))

    def test_environment_variables_override_root_inbox_and_vault(self) -> None:
        overrides = {
            ENV_ROOT: "D:/ko-data",
            ENV_INBOX: "D:/ko-inbox",
            ENV_OBSIDIAN_VAULT: "D:/ko-vault",
        }
        with patch.dict("os.environ", overrides, clear=True):
            paths = PipelinePaths.defaults(home=Path("C:/Users/example"))

        self.assertEqual(paths.staging, Path("D:/ko-data/staging"))
        self.assertEqual(paths.state, Path("D:/ko-data/state"))
        self.assertEqual(paths.inbox, Path("D:/ko-inbox"))
        self.assertEqual(paths.obsidian_vault, Path("D:/ko-vault"))

    def test_under_root_ignores_environment_overrides_for_isolated_test_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.dict("os.environ", {ENV_ROOT: "D:/should-not-be-used"}, clear=True):
                paths = PipelinePaths.under(root)

        self.assertEqual(paths.staging, root / "staging")
        self.assertEqual(paths.obsidian_vault, root / "vault")


class BrokerSettingsEnvironmentOverrideTests(unittest.TestCase):
    def test_default_base_url_without_override(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            settings = BrokerSettings()

        self.assertEqual(settings.base_url, "http://broker-machine.local:8080")

    def test_environment_variable_overrides_broker_base_url(self) -> None:
        with patch.dict("os.environ", {ENV_BROKER_URL: "http://ollama-host.lan:9000"}, clear=True):
            settings = BrokerSettings()

        self.assertEqual(settings.base_url, "http://ollama-host.lan:9000")

    def test_explicit_base_url_argument_wins_over_environment(self) -> None:
        with patch.dict("os.environ", {ENV_BROKER_URL: "http://ollama-host.lan:9000"}, clear=True):
            settings = BrokerSettings(base_url="http://explicit.test")

        self.assertEqual(settings.base_url, "http://explicit.test")

    def test_admin_token_is_none_without_environment_override(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            settings = BrokerSettings()

        self.assertIsNone(settings.admin_token)

    def test_environment_variable_sets_admin_token(self) -> None:
        with patch.dict("os.environ", {ENV_BROKER_ADMIN_TOKEN: "secret-token"}, clear=True):
            settings = BrokerSettings()

        self.assertEqual(settings.admin_token, "secret-token")


if __name__ == "__main__":
    unittest.main()
