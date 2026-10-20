"""Conexión con AI OS Core sin pegar tokens.

Core genera un token por app y lo deja, con su URL, en %LOCALAPPDATA%/AIOSCore/conexion.
Con eso, KO pide a Core el token del AI Broker, que el Broker rota en cada arranque y el
runner de Agora publica en Core. Solo biblioteca estándar: lo usa también `config`.
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

PRINCIPAL = "knowledge_orchestrator"


def core_connection(principal: str = PRINCIPAL) -> tuple[str, str] | None:
    """URL y token de esta app en Core, o None si Core no ha arrancado nunca en este equipo."""
    local = os.environ.get("LOCALAPPDATA")
    folder = os.environ.get("AI_OS_CONNECT_DIR") or (str(Path(local, "AIOSCore", "conexion")) if local else "")
    if not folder:
        return None
    try:
        data = json.loads(Path(folder, f"{principal}.json").read_text(encoding="utf-8"))
        url, token = str(data["core_url"]), str(data["token"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return (url, token) if url and token else None


def core_settings() -> tuple[str | None, str | None]:
    """`KO_CORE_URL`/`KO_CORE_TOKEN` y, si faltan, los que deja Core al arrancar."""
    url = os.environ.get("KO_CORE_URL") or None
    token = os.environ.get("KO_CORE_TOKEN") or None
    found = core_connection()
    if found and (not url or url.rstrip("/") == found[0].rstrip("/")):
        url, token = url or found[0], token or found[1]
    return url, token


class CoreBrokerToken:
    """El token del AI Broker, pedido a Core en cada petición; `refresh=True` tras un 401/403."""

    def __init__(self, core_url: str, core_token: str, timeout: float = 5.0) -> None:
        self._url = core_url.rstrip("/") + "/api/v1/credentials/broker"
        self._core_token = core_token
        self._timeout = timeout
        self._token: str | None = None

    def __call__(self, refresh: bool = False) -> str | None:
        if refresh or self._token is None:
            self._token = self._fetch() or self._token
        return self._token

    def _fetch(self) -> str | None:
        request = urllib.request.Request(self._url, headers={
            "Authorization": f"Bearer {self._core_token}", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310 - URL de Core
                token = json.load(response).get("token")
        except (OSError, ValueError, AttributeError):
            return None
        return token if isinstance(token, str) and token else None
