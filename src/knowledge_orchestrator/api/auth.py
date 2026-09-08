"""Credenciales solo en memoria; los eventos registran el nombre del consumidor."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ApiClient:
    name: str
    scopes: frozenset[str]
    token_hash: bytes = field(repr=False)


class ApiAuth:
    def __init__(self, clients: list[dict]) -> None:
        self.clients: list[ApiClient] = []
        names, hashes = set(), set()
        if not isinstance(clients, list) or not 1 <= len(clients) <= 64:
            raise ValueError('Configure entre 1 y 64 consumidores API')
        for client in clients:
            if not isinstance(client, dict) or set(client) != {'name', 'token', 'scopes'}:
                raise ValueError('Configuración de consumidor API inválida')
            name, token, scopes = client['name'], client['token'], client['scopes']
            if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', name):
                raise ValueError('Nombre de consumidor inválido')
            if not isinstance(token, str) or not 32 <= len(token) <= 256 or not token.isascii() or any(
                char.isspace() for char in token
            ):
                raise ValueError('Los tokens requieren 32–256 caracteres ASCII sin espacios')
            if not isinstance(scopes, list) or not scopes or any(
                s not in {'read', 'query', 'ingest', 'sources', 'review', 'governance'} for s in scopes
            ):
                raise ValueError('Permisos válidos: read, query, ingest, sources, review, governance')
            token_hash = hashlib.sha256(token.encode()).digest()
            if name in names or token_hash in hashes:
                raise ValueError('Consumidor o token duplicado')
            names.add(name)
            hashes.add(token_hash)
            self.clients.append(ApiClient(name, frozenset(scopes), token_hash))

    @classmethod
    def from_environment(cls) -> ApiAuth:
        try:
            raw = json.loads(os.environ.get('KO_API_CLIENTS', '[]'))
            return cls(raw)
        except (ValueError, TypeError, KeyError) as error:
            raise ValueError('KO_API_CLIENTS no contiene consumidores válidos') from error

    def authenticate(self, header: str) -> ApiClient | None:
        scheme, _, value = header.partition(' ')
        if scheme.lower() != 'bearer' or not 32 <= len(value) <= 256:
            return None
        digest = hashlib.sha256(value.encode()).digest()
        selected = None
        for client in self.clients:
            if hmac.compare_digest(client.token_hash, digest):
                selected = client
        return selected
