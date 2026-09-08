"""Procedencia compartida por consultas y propuestas; no confía en etiquetas ingeridas."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from urllib.parse import urlsplit, urlunsplit

from knowledge_orchestrator.repositories.database import Database


def source_provenance(database: Database, capture_id: str) -> dict:
    with closing(database.connect(readonly=True)) as connection:
        return source_provenance_in(connection, capture_id)


def source_provenance_in(connection: sqlite3.Connection, capture_id: str) -> dict:
    """Permite evaluar procedencia dentro de la misma transacción que una autorización."""
    row = connection.execute('SELECT capture_id,title,source_type,source_origin,metadata_json,sha256 FROM captures '
                             'WHERE capture_id=?', (capture_id,)).fetchone()
    if row is None:
        raise LookupError('Fuente inexistente')
    payload = dict(row)
    capture_hash = payload.pop('sha256')
    metadata = json.loads(payload.pop('metadata_json'))
    payload['captured_at'] = metadata.get('captured_at')
    payload['published_date'] = metadata.get('published_date')
    monitored = connection.execute(
        'SELECT s.provenance_json,s.observed_at,i.markdown_text FROM source_changes s JOIN api_ingestions i '
        'ON i.ingestion_id=s.ingestion_id WHERE i.capture_id=?', (capture_id,)).fetchone()
    if monitored and hashlib.sha256(monitored['markdown_text'].encode()).hexdigest() != capture_hash:
        payload['provenance_warning'] = 'CAPTURE_CHANGED_AFTER_RECEIPT'
    elif monitored:
        payload['monitoring'] = {
            **json.loads(monitored['provenance_json']), 'observed_at': monitored['observed_at'],
            'verification': 'source_trust_is_not_factual_verification'}
    raw_url = metadata.get('source_url')
    if isinstance(raw_url, str):
        url = urlsplit(raw_url)
        if url.scheme in {'http', 'https'} and url.hostname and not url.username and not url.password:
            payload['source_url'] = urlunsplit((url.scheme, url.netloc, url.path, '', ''))
    return payload
