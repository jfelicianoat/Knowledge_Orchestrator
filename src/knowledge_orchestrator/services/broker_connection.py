"""Configuración local y credencial protegida para conectar con AI Broker."""
from __future__ import annotations

import ctypes
import json
import os
from collections.abc import Callable
from ctypes import wintypes
from urllib.parse import urlsplit

from knowledge_orchestrator.config import (
    ENV_BROKER_ADMIN_TOKEN,
    ENV_BROKER_URL,
    BrokerSettings,
    PipelinePaths,
)
from knowledge_orchestrator.services.filesystem import atomic_write_json

DEFAULT_BROKER_URL = "http://192.168.1.52:8765"
CONNECTION_FILE = "broker_connection.json"
TOKEN_FILE = "broker-token.dpapi"


class BrokerConnectionError(ValueError):
    pass


class _DataBlob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def normalize_broker_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    try:
        port = parsed.port
    except ValueError as error:
        raise BrokerConnectionError("El puerto del Broker no es válido") from error
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise BrokerConnectionError("La dirección debe empezar por http:// o https:// e incluir un servidor")
    if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise BrokerConnectionError("Introduce solo la dirección base, sin credenciales, rutas ni parámetros")
    if port is None:
        raise BrokerConnectionError("La dirección del Broker debe incluir el puerto")
    return normalized


def _protect_windows(data: bytes) -> bytes:
    if os.name != "nt":
        raise BrokerConnectionError("El almacenamiento protegido solo está disponible en Windows")
    return _crypt_windows(data, protect=True)


def _unprotect_windows(data: bytes) -> bytes:
    if os.name != "nt":
        raise BrokerConnectionError("El almacenamiento protegido solo está disponible en Windows")
    return _crypt_windows(data, protect=False)


def _crypt_windows(data: bytes, *, protect: bool) -> bytes:
    source_buffer = ctypes.create_string_buffer(data)
    source = _DataBlob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    destination = _DataBlob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    operation = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    operation.argtypes = [
        ctypes.POINTER(_DataBlob), ctypes.c_wchar_p, ctypes.POINTER(_DataBlob),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob),
    ]
    operation.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if not operation(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(destination)):
        raise BrokerConnectionError(f"Windows no pudo proteger la credencial (error {ctypes.get_last_error()})")
    try:
        return ctypes.string_at(destination.data, destination.size)
    finally:
        kernel32.LocalFree(ctypes.cast(destination.data, ctypes.c_void_p))


class BrokerConnectionStore:
    """Guarda el endpoint sin secreto y cifra el token para el usuario de Windows."""

    def __init__(
        self,
        paths: PipelinePaths,
        *,
        protect: Callable[[bytes], bytes] = _protect_windows,
        unprotect: Callable[[bytes], bytes] = _unprotect_windows,
    ) -> None:
        self.connection_path = paths.state / CONNECTION_FILE
        self.token_path = paths.state / "credentials" / TOKEN_FILE
        self._protect = protect
        self._unprotect = unprotect

    def load_url(self) -> str | None:
        if not self.connection_path.exists():
            return None
        try:
            payload = json.loads(self.connection_path.read_text(encoding="utf-8"))
            value = payload.get("broker_url") if isinstance(payload, dict) else None
            return normalize_broker_url(value) if isinstance(value, str) else None
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def load_token(self) -> str | None:
        if not self.token_path.exists():
            return None
        try:
            return self._unprotect(self.token_path.read_bytes()).decode("utf-8") or None
        except (OSError, UnicodeError, BrokerConnectionError):
            return None

    def save(self, base_url: str, *, token: str | None = None) -> None:
        atomic_write_json(self.connection_path, {"broker_url": normalize_broker_url(base_url)})
        if token is not None:
            normalized_token = token.strip()
            if not normalized_token:
                raise BrokerConnectionError("El token no puede estar vacío")
            self.token_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.token_path.with_suffix(self.token_path.suffix + ".tmp")
            temporary.write_bytes(self._protect(normalized_token.encode("utf-8")))
            os.replace(temporary, self.token_path)

    def clear_token(self) -> None:
        self.token_path.unlink(missing_ok=True)

    def has_stored_token(self) -> bool:
        return self.token_path.is_file()


def load_broker_settings(paths: PipelinePaths) -> BrokerSettings:
    store = BrokerConnectionStore(paths)
    base_url = os.environ.get(ENV_BROKER_URL) or store.load_url() or DEFAULT_BROKER_URL
    admin_token = os.environ.get(ENV_BROKER_ADMIN_TOKEN) or store.load_token()
    return BrokerSettings(base_url=base_url, admin_token=admin_token)
