from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_orchestrator.config import ENV_BROKER_ADMIN_TOKEN, ENV_BROKER_URL, PipelinePaths
from knowledge_orchestrator.services.broker_connection import (
    DEFAULT_BROKER_URL,
    BrokerConnectionError,
    BrokerConnectionStore,
    load_broker_settings,
    normalize_broker_url,
)


class BrokerConnectionStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.paths = PipelinePaths.under(Path(self.temporary.name))
        self.paths.ensure_directories()
        self.store = BrokerConnectionStore(
            self.paths,
            protect=lambda value: b"protected:" + value[::-1],
            unprotect=lambda value: value.removeprefix(b"protected:")[::-1],
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_saves_endpoint_separately_and_never_writes_plain_token(self) -> None:
        self.store.save("http://192.168.1.52:8765/", token="secret-token")

        self.assertEqual(self.store.load_url(), "http://192.168.1.52:8765")
        self.assertEqual(self.store.load_token(), "secret-token")
        self.assertNotIn("secret-token", self.store.connection_path.read_text(encoding="utf-8"))
        self.assertNotIn(b"secret-token", self.store.token_path.read_bytes())

    def test_rejects_credentials_paths_and_missing_port_in_endpoint(self) -> None:
        for value in (
            "broker.local:8765",
            "http://broker.local",
            "http://user:pass@broker.local:8765",
            "http://broker.local:8765/api",
        ):
            with self.subTest(value=value), self.assertRaises(BrokerConnectionError):
                normalize_broker_url(value)

    def test_environment_has_precedence_over_local_endpoint(self) -> None:
        self.store.save("http://192.168.1.20:8765")
        with patch.dict(
            "os.environ",
            {ENV_BROKER_URL: "http://192.168.1.30:9000", ENV_BROKER_ADMIN_TOKEN: "environment-token"},
            clear=True,
        ):
            settings = load_broker_settings(self.paths)

        self.assertEqual(settings.base_url, "http://192.168.1.30:9000")
        self.assertEqual(settings.admin_token, "environment-token")

    def test_default_points_to_the_documented_broker(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            settings = load_broker_settings(self.paths)

        self.assertEqual(DEFAULT_BROKER_URL, "http://192.168.1.52:8765")
        self.assertEqual(settings.base_url, DEFAULT_BROKER_URL)
