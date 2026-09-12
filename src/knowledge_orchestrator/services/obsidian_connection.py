"""Conexión al editor local con credencial DPAPI independiente del Broker."""
from __future__ import annotations

import base64
import json
from collections.abc import Callable
from pathlib import Path

from knowledge_orchestrator.config import PipelinePaths
from knowledge_orchestrator.integrations.obsidian_bridge import (
    DEFAULT_BRIDGE_URL,
    ObsidianBridgeClient,
    ObsidianBridgeUnavailable,
)
from knowledge_orchestrator.services.broker_connection import _protect_windows, _unprotect_windows
from knowledge_orchestrator.services.filesystem import atomic_write_json


class ObsidianConnection:
    def __init__(self, paths: PipelinePaths, *, protect: Callable[[bytes], bytes] = _protect_windows,
                 unprotect: Callable[[bytes], bytes] = _unprotect_windows) -> None:
        self.vault = paths.obsidian_vault
        self.path = paths.state / 'credentials' / 'obsidian-bridge.json'
        self._protect, self._unprotect = protect, unprotect

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(data, dict) or set(data) != {'url', 'credential', 'vault_id'}:
                raise ValueError
            if any(not isinstance(value, str) for value in data.values()):
                raise ValueError
            return data
        except (OSError, ValueError):
            raise ObsidianBridgeUnavailable('Configura la conexión protegida con Obsidian en Ajustes') from None

    def client(self) -> ObsidianBridgeClient:
        data = self._load()
        try:
            token = self._unprotect(base64.b64decode(data['credential'], validate=True)).decode('utf-8')
            client = ObsidianBridgeClient(self.vault, token, base_url=data['url'])
            if data['vault_id'] != client.vault_id:
                raise ValueError
            return client
        except (ValueError, TypeError, OSError):
            raise ObsidianBridgeUnavailable('Revisa la conexión de Obsidian para esta bóveda y usuario') from None

    def save(self, base_url: str, *, token: str | None = None) -> None:
        try:
            if token is None:
                token = self.client()._token
            client = ObsidianBridgeClient(self.vault, token, base_url=base_url.strip().rstrip('/'))
            protected = self._protect(token.encode('utf-8'))
            atomic_write_json(self.path, {'url': client.base_url, 'vault_id': client.vault_id,
                                         'credential': base64.b64encode(protected).decode('ascii')})
        except (ValueError, OSError):
            raise ObsidianBridgeUnavailable(
                'No se pudo guardar: usa una dirección local con puerto y una clave de al menos 32 caracteres'
            ) from None

    def configured_url(self) -> str:
        try:
            return self.client().base_url
        except ObsidianBridgeUnavailable:
            # An existing bridge may use the former default or a chosen port.
            # This is only a UI suggestion; no credential is read or connection saved.
            settings = self.vault / '.obsidian' / 'plugins' / 'knowledge-orchestrator-bridge' / 'data.json'
            try:
                with settings.open(encoding='utf-8') as stream:
                    data = json.loads(stream.read(65536))
                port = data.get('port') if isinstance(data, dict) else None
                if type(port) is int and 1024 <= port <= 65535:
                    return f'http://127.0.0.1:{port}'
            except (OSError, ValueError):
                pass
            return DEFAULT_BRIDGE_URL

    def status(self) -> dict:
        return self.client().status()

    def replace(self, path: Path, content: str, *, base_hash: str, result_hash: str, request_id: str) -> dict:
        return self.client().replace(path, content, base_hash=base_hash, result_hash=result_hash,
                                     request_id=request_id)
