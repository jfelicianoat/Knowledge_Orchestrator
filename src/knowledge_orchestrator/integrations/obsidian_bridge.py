"""Cliente local para reemplazo condicional mediante el editor Obsidian."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx


class ObsidianBridgeUnavailable(RuntimeError):
    pass


class ObsidianBridgeConflict(ValueError):
    pass


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class ObsidianBridgeClient:
    def __init__(self, vault: Path, token: str, *, base_url: str = 'http://127.0.0.1:8766',
                 transport: httpx.BaseTransport | None = None) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.port is None \
                or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            raise ValueError('El puente debe estar en http://127.0.0.1 con un puerto explícito')
        if len(token) < 32 or any(character in token for character in '\r\n'):
            raise ValueError('La credencial del puente debe tener al menos 32 caracteres y una sola línea')
        self.vault = vault.resolve()
        self.vault_id = _hash(str(self.vault).replace('\\', '/').lower().encode('utf-8'))
        self.base_url = base_url
        self._token = token
        self._transport = transport

    def _request(self, method: str, endpoint: str, payload: dict | None = None) -> dict[str, Any]:
        try:
            with httpx.Client(base_url=self.base_url, timeout=20, transport=self._transport,
                              trust_env=False, follow_redirects=False, headers={
                                  'Authorization': f'Bearer {self._token}', 'X-KO-Vault-ID': self.vault_id,
                              }) as client:
                response = client.request(method, endpoint, json=payload)
        except httpx.HTTPError:
            raise ObsidianBridgeUnavailable('No se pudo contactar con el puente local de Obsidian') from None
        if response.status_code in {404, 409}:
            raise ObsidianBridgeConflict('La nota, bóveda o recibo requieren revisión antes de continuar')
        if response.status_code != 200:
            raise ObsidianBridgeUnavailable('El puente de Obsidian no aceptó la operación')
        try:
            result = response.json()
        except ValueError:
            raise ObsidianBridgeUnavailable('El puente devolvió una respuesta inválida') from None
        if not isinstance(result, dict):
            raise ObsidianBridgeUnavailable('El puente devolvió una respuesta inválida')
        return result

    def status(self) -> dict[str, Any]:
        result = self._request('GET', '/v1/status')
        if result.get('protocol') != 1 or result.get('vault_id') != self.vault_id:
            raise ObsidianBridgeConflict('El puente no corresponde a la bóveda configurada')
        return result

    def replace(self, path: Path, content: str, *, base_hash: str, result_hash: str, request_id: str) -> dict:
        try:
            relative = path.resolve().relative_to(self.vault).as_posix()
        except ValueError:
            raise ObsidianBridgeConflict('La nota no pertenece a la bóveda configurada') from None
        if _hash(content.encode('utf-8')) != result_hash:
            raise ObsidianBridgeConflict('El resultado no coincide con la intención de publicación')
        result = self._request('POST', '/v1/apply', {
            'request_id': request_id, 'path': relative, 'base_hash': base_hash,
            'result_hash': result_hash, 'content': content,
        })
        if result.get('request_id') != request_id or result.get('result_hash') != result_hash \
                or result.get('status') not in {'applied', 'already_applied'}:
            raise ObsidianBridgeUnavailable('El recibo no corresponde a la intención de publicación')
        # A receipt describes a completed operation, not the current state. A human
        # may have edited the note after Obsidian wrote it and before we received it.
        try:
            current_hash = _hash(path.read_bytes())
        except OSError:
            raise ObsidianBridgeConflict('No se pudo comprobar la nota después del recibo') from None
        if current_hash != result_hash:
            raise ObsidianBridgeConflict('La nota cambió después de la aplicación en Obsidian')
        return result
