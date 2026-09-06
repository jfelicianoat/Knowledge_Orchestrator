"""Recepción durable: registra la intención y entrega al inbox del flujo existente."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from contextlib import closing
from datetime import datetime, timezone
from urllib.parse import urlsplit

import yaml

from knowledge_orchestrator.config import PipelinePaths
from knowledge_orchestrator.domain.contracts import parse_capture_bytes
from knowledge_orchestrator.domain.knowledge import KnowledgeConflict
from knowledge_orchestrator.repositories.database import Database
from knowledge_orchestrator.services.filesystem import write_synced


class ApiIngestionService:
    def __init__(self, database: Database, paths: PipelinePaths) -> None:
        self.database = database
        self.paths = paths

    def create(self, payload: dict, *, owner: str, key: str) -> dict:
        title, content = payload['title'], payload['content']
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 500 \
                or not isinstance(content, str) or not 1 <= len(content.strip()) <= 500000:
            raise ValueError('Título o contenido inválido')
        source_url = payload.get('source_url')
        if source_url is not None:
            url = urlsplit(source_url)
            if url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password:
                raise ValueError('source_url requiere HTTP(S) sin credenciales')
        payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        identity = hashlib.sha256(json.dumps([owner, key_hash]).encode()).hexdigest()
        capture_id = 'api_' + identity[:40]
        metadata = {'contract_version': '1.0', 'capture_id': capture_id, 'source_type': 'document',
                    'title': title.strip(), 'captured_at': datetime.now(timezone.utc).isoformat(),
                    'has_transcript': True, 'status': 'pending', 'api_client': owner}
        if source_url:
            metadata['source_url'] = source_url
        markdown = '---\n' + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=True) + \
            '---\n\n## Transcripción\n\n' + content + '\n'
        parse_capture_bytes(markdown.encode('utf-8'))
        with self.database.transaction(immediate=True) as connection:
            inserted = connection.execute(
                'INSERT INTO api_ingestions(ingestion_id, owner, key_hash, payload_hash, capture_id, markdown_text) '
                'VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(owner, key_hash) DO NOTHING',
                (identity, owner, key_hash, payload_hash, capture_id, markdown),
            )
            row = connection.execute(
                'SELECT * FROM api_ingestions WHERE owner = ? AND key_hash = ?', (owner, key_hash),
            ).fetchone()
            if row['payload_hash'] != payload_hash:
                raise KnowledgeConflict('Idempotency-Key ya utilizada con otro documento')
            if inserted.rowcount == 1:
                connection.execute(
                    "INSERT INTO events(event_type, message, details_json) VALUES "
                    "('API_INGESTION_RECEIVED', 'Documento recibido para ingesta controlada', ?)",
                    (json.dumps({'owner': owner, 'ingestion_id': identity, 'capture_id': capture_id}),),
                )
        return self.get(identity, owner=owner)

    def get(self, ingestion_id: str, *, owner: str) -> dict:
        with closing(self.database.connect(readonly=True)) as connection:
            row = connection.execute(
                'SELECT i.ingestion_id, i.capture_id, i.status, i.created_at, c.status AS capture_status '
                'FROM api_ingestions i LEFT JOIN captures c ON c.capture_id = i.capture_id '
                'WHERE i.ingestion_id = ? AND i.owner = ?', (ingestion_id, owner),
            ).fetchone()
            if row is None:
                raise LookupError('Ingesta inexistente')
            return dict(row)

    def deliver_pending(self) -> int:
        with closing(self.database.connect(readonly=True)) as connection:
            rows = connection.execute(
                "SELECT * FROM api_ingestions WHERE status = 'PENDING' ORDER BY created_at LIMIT 20"
            ).fetchall()
        count = 0
        for row in rows:
            with self.database.transaction(immediate=True) as connection:
                pending = connection.execute(
                    "SELECT 1 FROM api_ingestions WHERE ingestion_id = ? AND status = 'PENDING'",
                    (row['ingestion_id'],),
                ).fetchone()
                if not pending:
                    continue
                capture_exists = connection.execute(
                    'SELECT 1 FROM captures WHERE capture_id = ?', (row['capture_id'],),
                ).fetchone()
                if not capture_exists:
                    path = self.paths.inbox / (row['capture_id'] + '.md')
                    content = row['markdown_text'].encode('utf-8')
                    if path.exists() and path.read_bytes() != content:
                        connection.execute("UPDATE api_ingestions SET status = 'CONFLICT' WHERE ingestion_id = ?",
                                           (row['ingestion_id'],))
                        continue
                    if not path.exists():
                        temporary = path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
                        try:
                            write_synced(temporary, content)
                            os.replace(temporary, path)
                        finally:
                            temporary.unlink(missing_ok=True)
                connection.execute("UPDATE api_ingestions SET status = 'DELIVERED' WHERE ingestion_id = ?",
                                   (row['ingestion_id'],))
                connection.execute(
                    "INSERT INTO events(event_type, message, details_json) VALUES "
                    "('API_INGESTION_DELIVERED', 'Intención API entregada al flujo de ingesta', ?)",
                    (json.dumps({'ingestion_id': row['ingestion_id'], 'capture_id': row['capture_id']}),),
                )
            count += 1
        return count
