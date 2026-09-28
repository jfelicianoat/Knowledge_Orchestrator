"""Consumidores de la API dados de alta desde la aplicación.

La credencial se genera aquí, se devuelve una sola vez y no se guarda: en la
base solo queda `sha256(sal + credencial)`. Con 256 bits de azar en la
credencial, un hash rápido con sal basta —no hay contraseña humana que
proteger de un diccionario— y permite comprobar cada petición sin coste.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from dataclasses import dataclass, field

from .database import Database

#: Los mismos permisos que acepta `ApiAuth`; se repiten para no importar la capa API.
VALID_SCOPES = frozenset({'read', 'query', 'ingest', 'sources', 'review', 'governance'})
NAME_PATTERN = re.compile(r'[A-Za-z0-9_.-]{1,64}')
MAX_ACTIVE_CONSUMERS = 64


@dataclass(frozen=True, slots=True)
class StoredConsumer:
    consumer_id: int
    name: str
    scopes: frozenset[str]
    created_at: str
    revoked_at: str | None
    token_salt: bytes = field(repr=False)
    token_hash: bytes = field(repr=False)


def _digest(salt: bytes, token: str) -> bytes:
    return hashlib.sha256(salt + token.encode('ascii')).digest()


def _consumer(row: sqlite3.Row) -> StoredConsumer:
    return StoredConsumer(
        consumer_id=int(row['consumer_id']), name=str(row['name']),
        scopes=frozenset(json.loads(row['scopes_json'])), created_at=str(row['created_at']),
        revoked_at=row['revoked_at'], token_salt=bytes(row['token_salt']), token_hash=bytes(row['token_hash']),
    )


class ApiConsumerRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(self, name: str, scopes: Iterable[str], *, reserved_names: Iterable[str] = ()) -> tuple[
            StoredConsumer, str]:
        """Da de alta un consumidor y devuelve su credencial, que no vuelve a estar disponible."""

        name = name.strip() if isinstance(name, str) else ''
        if not NAME_PATTERN.fullmatch(name):
            raise ValueError('El nombre admite 1–64 letras sin tildes, números, punto, guion o guion bajo.')
        chosen = sorted(set(scopes))
        if not chosen:
            raise ValueError('Elige al menos un permiso.')
        if any(scope not in VALID_SCOPES for scope in chosen):
            raise ValueError('Permiso desconocido.')
        if name in set(reserved_names):
            raise ValueError(f'Ya hay un consumidor «{name}» configurado fuera de la aplicación.')
        token = 'ko_' + secrets.token_urlsafe(32)
        salt = secrets.token_bytes(16)
        with self.database.transaction(immediate=True) as connection:
            active = connection.execute('SELECT count(*) FROM api_consumers WHERE revoked_at IS NULL').fetchone()[0]
            if active >= MAX_ACTIVE_CONSUMERS:
                raise ValueError(f'Como máximo {MAX_ACTIVE_CONSUMERS} consumidores activos.')
            try:
                cursor = connection.execute(
                    'INSERT INTO api_consumers(name, scopes_json, token_salt, token_hash) VALUES (?,?,?,?)',
                    (name, json.dumps(chosen), salt, _digest(salt, token)),
                )
            except sqlite3.IntegrityError:
                raise ValueError(f'Ya existe un consumidor activo llamado «{name}».') from None
            connection.execute(
                "INSERT INTO events(event_type, message, details_json) VALUES ('API_CONSUMER_CREATED', ?, ?)",
                (f'Consumidor API creado: {name}', json.dumps({'client': name, 'scopes': chosen})),
            )
            row = connection.execute('SELECT * FROM api_consumers WHERE consumer_id = ?',
                                     (cursor.lastrowid,)).fetchone()
        return _consumer(row), token

    def revoke(self, name: str) -> bool:
        with self.database.transaction(immediate=True) as connection:
            changed = connection.execute(
                "UPDATE api_consumers SET revoked_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                'WHERE name = ? AND revoked_at IS NULL', (name,),
            ).rowcount
            if changed:
                connection.execute(
                    "INSERT INTO events(event_type, message, details_json) VALUES ('API_CONSUMER_REVOKED', ?, ?)",
                    (f'Acceso API revocado: {name}', json.dumps({'client': name})),
                )
            return bool(changed)

    def active(self) -> list[StoredConsumer]:
        with closing(self.database.connect(readonly=True)) as connection:
            rows = connection.execute(
                'SELECT * FROM api_consumers WHERE revoked_at IS NULL ORDER BY name').fetchall()
        return [_consumer(row) for row in rows]

    def authenticate(self, token: str) -> StoredConsumer | None:
        """Se lee la base en cada petición: revocar surte efecto en la siguiente."""

        if not token.isascii():
            return None
        selected = None
        for consumer in self.active():
            # Se recorren todos, sin salir al primero, para no filtrar por tiempos.
            if hmac.compare_digest(consumer.token_hash, _digest(consumer.token_salt, token)):
                selected = consumer
        return selected
