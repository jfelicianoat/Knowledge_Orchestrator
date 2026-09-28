"""Credenciales de la API; los eventos registran el nombre del consumidor, nunca el token.

Hay dos orígenes y se suman: los consumidores de `KO_API_CLIENTS` (en memoria,
fijados al iniciar el listener) y los creados desde la aplicación (en SQLite,
solo su hash con sal, leídos en cada petición para que revocar sea inmediato).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from knowledge_orchestrator.repositories.api_consumer_repository import ApiConsumerRepository


@dataclass(frozen=True, slots=True)
class ApiClient:
    name: str
    scopes: frozenset[str]
    token_hash: bytes = field(repr=False)
    origin: str = 'environment'


class ApiAuth:
    def __init__(self, clients: list[dict], *, store: ApiConsumerRepository | None = None) -> None:
        self.clients: list[ApiClient] = []
        self.store = store
        names, hashes = set(), set()
        # Sin almacén, la variable de entorno es la única fuente y no puede venir vacía.
        minimum = 0 if store is not None else 1
        if not isinstance(clients, list) or not minimum <= len(clients) <= 64:
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
    def from_environment(cls, store: ApiConsumerRepository | None = None) -> ApiAuth:
        """Consumidores de `KO_API_CLIENTS` más los del almacén; exige al menos uno en total."""

        try:
            raw = json.loads(os.environ.get('KO_API_CLIENTS', '[]'))
            auth = cls(raw, store=store)
        except (ValueError, TypeError, KeyError) as error:
            raise ValueError('KO_API_CLIENTS no contiene consumidores válidos') from error
        if not auth.all_clients():
            raise ValueError('No hay consumidores API configurados')
        return auth

    def all_clients(self) -> list[ApiClient]:
        """Los de entorno y los activos del almacén, tal como están ahora."""

        stored = [
            ApiClient(consumer.name, consumer.scopes, consumer.token_hash, origin='application')
            for consumer in (self.store.active() if self.store is not None else [])
        ]
        return [*self.clients, *stored]

    def authenticate(self, header: str) -> ApiClient | None:
        scheme, _, value = header.partition(' ')
        if scheme.lower() != 'bearer' or not 32 <= len(value) <= 256:
            return None
        digest = hashlib.sha256(value.encode()).digest()
        selected = None
        for client in self.clients:
            if hmac.compare_digest(client.token_hash, digest):
                selected = client
        if selected is None and self.store is not None:
            consumer = self.store.authenticate(value)
            if consumer is not None:
                selected = ApiClient(consumer.name, consumer.scopes, consumer.token_hash, origin='application')
        return selected
