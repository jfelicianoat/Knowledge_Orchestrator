from __future__ import annotations

import sqlite3
import time
from collections.abc import Mapping

from knowledge_orchestrator.domain.knowledge import KnowledgeConflict
from knowledge_orchestrator.domain.monitoring import SourceConfig, SourceError
from knowledge_orchestrator.integrations.source_connectors import Connector, RssConnector, WebConnector
from knowledge_orchestrator.repositories.source_repository import SourceRepository
from knowledge_orchestrator.services.api_ingestion import ApiIngestionService

MONITOR_OWNER = 'internal:source-monitor'  # ':' is forbidden in external API consumer names.


class SourceMonitoringService:
    def __init__(self, repository: SourceRepository, ingestion: ApiIngestionService,
                 connectors: Mapping[str, Connector] | None = None):
        self.repository, self.ingestion = repository, ingestion
        self.connectors = connectors if connectors is not None else {'web': WebConnector(), 'rss': RssConnector()}

    def check(self, job: dict) -> bool:
        result, error = None, None
        try:
            config = SourceConfig(**job['config'])
            result = self.connectors[config.kind].fetch(config, etag=job['etag'], last_modified=job['last_modified'])
        except SourceError as failure:
            error = failure.code
        except Exception:
            error = 'CONNECTOR_ERROR'
        return self.repository.finish(job, result, now=time.time(), error=error)

    def deliver_ready(self) -> int:
        delivered = 0
        for item in self.repository.changes(status='READY', limit=20, delivery_due=time.time()):
            change = self.repository.change(item['change_id'])
            try:
                receipt = self.ingestion.create({'title': change['title'], 'content': change['content'],
                                                 'source_url': change['source_url']},
                                                owner=MONITOR_OWNER, key=change['change_id'])
                # Crash between create and link reuses the same durable ingestion, never creates another capture.
                self.repository.delivered(change['change_id'], receipt['ingestion_id'])
                delivered += 1
            except (OSError, sqlite3.Error, ValueError, KnowledgeConflict):
                self.repository.delivery_failed(change['change_id'])
        return delivered
