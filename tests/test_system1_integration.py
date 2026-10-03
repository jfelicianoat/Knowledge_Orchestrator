from __future__ import annotations

import asyncio
import json
import unittest
from contextlib import closing
from unittest.mock import patch

from knowledge_orchestrator.api.contracts import QUERY, validate
from knowledge_orchestrator.integrations.broker_client import TransientBrokerError
from knowledge_orchestrator.services.knowledge_query import KnowledgeQueryProcessor
from knowledge_orchestrator.services.system1 import System1Service
from knowledge_orchestrator.services.system1_settings import System1Settings
from tests import test_phase_six_semantic_maintenance as phase_six
from tests.helpers import valid_markdown
from tests.test_phase_ten_knowledge_api import FakeQueryBroker
from tests.test_system1 import FakeJudge, candidates, transcript_fixture


class System1IntegrationTests(unittest.IsolatedAsyncioTestCase):
    setUp = phase_six.PhaseSixSemanticMaintenanceTests.setUp
    tearDown = phase_six.PhaseSixSemanticMaintenanceTests.tearDown
    publish = phase_six.PhaseSixSemanticMaintenanceTests.publish
    extraction = staticmethod(phase_six.PhaseSixSemanticMaintenanceTests.extraction)

    async def test_vector_retrieval_precedes_judgments_and_generator_sees_only_final_candidates(self):
        service = self.runtime.knowledge_queries
        original = candidates()
        broker = FakeJudge({10: 10, 11: 8})
        service.system1 = System1Service(broker, System1Settings(rag_enabled=True))
        retrieval = {'vector': [1, 0], 'model': 'embedding-space'}
        validate({'question': '¿Resultado exacto?', 'retrieval': retrieval}, QUERY)
        with patch.object(service.access, 'semantic_search', return_value=[
                {'score': 1 - i * 0.01, 'claim': c} for i, c in enumerate(original)]) as vector_search:
            created = service.create('¿Resultado exacto?', state='current', owner='consumer',
                                     key='vector-query-001', retrieval=retrieval)
        vector_search.assert_called_once_with([1, 0], 'embedding-space', state='current', limit=24)
        self.assertEqual(broker.requests, [])
        generator = FakeQueryBroker({'claim_ids': [10], 'insufficient': False})
        processor = KnowledgeQueryProcessor(service, generator)
        self.assertEqual(await processor.dispatch_once(), 1)
        row = service.repository.get(created['query_id'])
        snapshot = json.loads(row['snapshot_json'])
        self.assertEqual(snapshot['retrieval'], 'vector_cosine')
        self.assertEqual([c['claim_id'] for c in snapshot['claims']], [10, 11])
        self.assertEqual(generator.requests[0], json.loads(row['request_json']))
        self.assertEqual(len(broker.requests), 12)
        self.assertIn('Evidencia exacta', generator.requests[0]['content']['prompt'])
        self.assertNotIn('"claim_id": 1,', generator.requests[0]['content']['prompt'])
        with closing(self.runtime.database.connect()) as connection:
            event = connection.execute("SELECT details_json FROM events WHERE event_type='SYSTEM1_RAG_PREPARED'").                fetchone()[0]
        self.assertNotIn('¿Resultado exacto?', event)
        self.assertNotIn('quote', event)
        # Otro vector bajo la misma clave no puede reutilizar una respuesta ajena.
        with self.assertRaises(ValueError):
            validate({'question': 'x', 'retrieval': {'vector': [True], 'model': 'space'}}, QUERY)

    async def test_prepared_request_survives_restart_and_retry_without_new_judgments(self):
        service = self.runtime.knowledge_queries
        broker = FakeJudge({10: 10})
        service.system1 = System1Service(broker, System1Settings(rag_enabled=True))
        with patch.object(service.access, 'search', return_value=candidates()):
            created = service.create('consulta', state='current', owner='consumer', key='retry-query-001')
        row = service.repository.claim(created['query_id'])
        prepared = await service.prepare_system1(row)
        first_body = prepared['request_json']
        first_key = json.loads(first_body)['idempotency_key']
        service.repository.recover()
        row = service.repository.claim(created['query_id'])
        restored = await service.prepare_system1(row)
        self.assertEqual(restored['request_json'], first_body)
        self.assertEqual(json.loads(restored['request_json'])['idempotency_key'], first_key)
        self.assertEqual(len(broker.requests), 12)

    async def test_knowledge_changes_during_judge_block_stale_evidence(self):
        service = self.runtime.knowledge_queries
        service.system1 = System1Service(FakeJudge(), System1Settings(rag_enabled=True))
        with patch.object(service.access, 'search', return_value=candidates()):
            created = service.create('consulta', state='current', owner='consumer', key='stale-query-001')
        generator = FakeQueryBroker({'claim_ids': [], 'insufficient': True})
        with patch.object(service, 'fingerprint', return_value='changed'):
            self.assertEqual(await KnowledgeQueryProcessor(service, generator).dispatch_once(), 0)
        self.assertEqual(service.repository.get(created['query_id'])['status'], 'STALE')
        self.assertEqual(generator.requests, [])

    async def test_broker_failure_during_rerank_preserves_original_request(self):
        service = self.runtime.knowledge_queries
        service.system1 = System1Service(FakeJudge(error=TransientBrokerError('offline')),
                                         System1Settings(rag_enabled=True))
        with patch.object(service.access, 'search', return_value=candidates()):
            created = service.create('consulta', state='current', owner='consumer', key='fallback-query-001')
        row = service.repository.claim(created['query_id'])
        prepared = await service.prepare_system1(row)
        self.assertEqual(prepared['request_json'], row['request_json'])
        self.assertEqual(json.loads(prepared['snapshot_json'])['claims'], candidates())
        self.assertTrue(json.loads(prepared['snapshot_json'])['system1']['fallback'])

    async def test_youtube_worker_preparation_preserves_source_and_persists_segment_trace(self):
        capture_id = 'yt_system1_video'
        text = transcript_fixture()
        document = valid_markdown(capture_id=capture_id).decode().replace(
            '[00:00:00] Contenido de prueba.', text)
        source = self.runtime.paths.inbox / (capture_id + '.md')
        source.write_text(document, encoding='utf-8')
        self.assertTrue(self.runtime.ingestion.ingest(source).accepted)
        capture = self.runtime.repository.get(capture_id)
        original = capture.transcript_content
        planner = self.runtime.workflow_planner
        planner.system1 = System1Service(FakeJudge({'S2': 'promotion'}), System1Settings(
            transcript_enabled=True, segment_tokens=40, adjacent_segments=0))
        planned = await planner.plan_unplanned_async()
        self.assertEqual(len(planned), 1)
        workflow = self.runtime.workflow_repository.get_workflow(planned[0])
        self.assertIn('system1', json.loads(workflow.plan_json))
        task = self.runtime.workflow_repository.list_workflow_tasks(planned[0])[0]
        self.assertNotIn('Patrocinio', json.loads(task.request_json)['content']['prompt'])
        self.assertEqual(self.runtime.repository.get(capture_id).transcript_content, original)
        self.assertEqual(planner.workflows.list_unplanned_capture_ids(), [])

    async def test_enabled_recovery_leaves_new_captures_for_async_worker(self):
        capture_id = 'yt_system1_recovery'
        source = self.runtime.paths.inbox / (capture_id + '.md')
        source.write_bytes(valid_markdown(capture_id=capture_id))
        self.assertTrue(self.runtime.ingestion.ingest(source).accepted)
        self.runtime.workflow_planner.system1 = System1Service(FakeJudge(), System1Settings(transcript_enabled=True))
        self.runtime.recover_once(ingest_inbox=False)
        self.assertIn(capture_id, self.runtime.workflow_repository.list_unplanned_capture_ids())
        self.assertEqual(len(await self.runtime.workflow_planner.plan_unplanned_async()), 1)

    async def test_stop_interrupts_slow_judgment_without_submission(self):
        worker = self.runtime.broker_worker
        started, cancelled = asyncio.Event(), asyncio.Event()
        async def slow():
            started.set()
            try:
                await asyncio.sleep(20)
            finally:
                cancelled.set()
        operation = asyncio.create_task(worker._interruptible(slow()))
        await started.wait()
        worker._stop.set()
        self.assertEqual(await asyncio.wait_for(operation, 1), [])
        self.assertTrue(cancelled.is_set())
