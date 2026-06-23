from __future__ import annotations

from datetime import datetime, timezone

from knowledge_orchestrator.integrations.broker_client import BrokerClient
from knowledge_orchestrator.repositories.workflow_repository import WorkflowRepository


class ModelDiscoveryService:
    def __init__(self, repository: WorkflowRepository, client: BrokerClient) -> None:
        self.repository = repository
        self.client = client

    async def refresh(self) -> int:
        models = await self.client.list_models()
        self.repository.upsert_models(models, datetime.now(timezone.utc).isoformat())
        return len(models)
