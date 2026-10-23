"""Índice de notas (21-oct-2026): fragmentos, lotes de embeddings del Broker 2.12 y recuperación."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import unittest
from contextlib import closing
from unittest.mock import patch

import httpx

from knowledge_orchestrator.api.application import KnowledgeApi
from knowledge_orchestrator.api.auth import ApiAuth
from knowledge_orchestrator.domain.broker_contracts import (
    BrokerContractError,
    failure_message,
    normalize_capabilities_response,
    validate_create_task_request,
    validate_task_status_response,
)
from knowledge_orchestrator.services.note_index import (
    FRAGMENT_CHARS,
    EmbeddingModel,
    NoteIndexProcessor,
    fragment_note,
)
from knowledge_orchestrator.services.semantic_broker import SemanticBrokerProcessor
from knowledge_orchestrator.services.semantic_maintenance.analisis import _validated_fields
from knowledge_orchestrator.services.semantic_maintenance.prompts import PromptsMixin
from tests import test_phase_six_semantic_maintenance as phase_six

TOKEN = 'test-api-only-reader-token-000000002'
MODEL = EmbeddingModel('ollama', 'local', 'bge-m3:latest')
#: Cada concepto se activa con varias palabras: así la pregunta puede no
#: compartir ni una palabra con la nota y aun así parecerse en el espacio vectorial.
CONCEPTS = (
    {'mcp', 'protocolo', 'conector', 'conectores'},
    {'receta', 'cocina', 'horno'},
    {'bolsa', 'inversión', 'acciones'},
    {'jardín', 'plantas', 'riego'},
)


def fake_vector(text: str) -> list[float]:
    words = set(text.casefold().replace('?', ' ').replace('¿', ' ').split())
    return [float(len(words & concept)) for concept in CONCEPTS] + [0.05]


class FakeEmbeddingBroker:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.failures: dict[str, dict] = {}

    async def create_task(self, request):
        validate_create_task_request(request)
        self.requests.append(request)
        return {'task_id': 'task-' + str(len(self.requests)), 'status_url': '/x'}

    async def get_task(self, task_id, *, status_url=None, operation_id=None):
        request = self.requests[int(task_id.split('-')[1]) - 1]
        if task_id in self.failures:
            return {'task_id': task_id, 'status': 'failed', 'error': self.failures.pop(task_id)}
        texts = request['content'].get('inputs') or [request['content']['prompt']]
        model = {'provider': 'ollama', 'deployment': 'local', 'model': 'bge-m3:latest', 'digest': 'abc'}
        if 'inputs' in request['content']:
            result = {'embeddings': [fake_vector(text) for text in texts], 'embedding_model': model}
        else:
            result = {'embedding': fake_vector(texts[0]), 'embedding_model': model}
        return {'task_id': task_id, 'status': 'completed', 'kind': 'embedding', 'result': result}


class NoteIndexTests(unittest.TestCase):
    tearDown = phase_six.PhaseSixSemanticMaintenanceTests.tearDown
    publish = phase_six.PhaseSixSemanticMaintenanceTests.publish

    def setUp(self):
        phase_six.PhaseSixSemanticMaintenanceTests.setUp(self)
        self.index = self.runtime.note_index
        self.index.capabilities = lambda: {'embedding_batch_max': 2}
        self.broker = FakeEmbeddingBroker()
        self.processor = NoteIndexProcessor(self.index, self.broker)
        app = KnowledgeApi(self.runtime, ApiAuth([{'name': 'reader', 'token': TOKEN, 'scopes': ['read']}]))
        self.client = httpx.Client(transport=httpx.WSGITransport(app), base_url='http://localhost/api/v1/')
        self.addCleanup(self.client.close)

    def cycle(self, times: int = 1) -> None:
        for _ in range(times):
            asyncio.run(self.processor.cycle())

    def seed(self):
        mcp = self.publish('nota_mcp', '# Integraciones\n\nMCP es un conector entre la IA y herramientas externas.\n')
        fillers = [
            self.publish(f'nota_{index}', f'# Tema {index}\n\n{text} número {index}.\n')
            for index, text in enumerate(['Una receta de cocina al horno', 'Las acciones de bolsa y la inversión',
                                          'El riego de las plantas del jardín'] * 4)
        ]
        return mcp, fillers

    def retrieve(self, question: str, key: str = 'retrieval-key-0001'):
        return self.client.post('retrievals', json={'question': question},
                                headers={'Authorization': 'Bearer ' + TOKEN, 'Idempotency-Key': key})

    def test_fragments_keep_every_word_and_respect_the_size(self):
        long_paragraph = ' '.join(f'Frase número {index} sobre el tema.' for index in range(200))
        document = f'---\ntitle: x\n---\n# Uno\n\nCorto.\n\nOtro corto.\n\n## Dos\n\n{long_paragraph}\n'
        fragments = fragment_note(document)
        self.assertEqual(fragments[0], ('Uno', 'Corto.\n\nOtro corto.'))
        self.assertTrue(all(len(text) <= FRAGMENT_CHARS for _heading, text in fragments))
        self.assertTrue(all(heading == 'Dos' for heading, _text in fragments[1:]))
        joined = ' '.join(text for _heading, text in fragments[1:]).split()
        self.assertEqual(joined, long_paragraph.split(), 'no se pierde ni se reordena texto')
        self.assertNotIn('title: x', ' '.join(text for _h, text in fragments), 'el frontmatter no se indexa')

    def test_batches_follow_the_broker_limit_and_store_one_vector_per_fragment(self):
        self.seed()
        self.index.set_model(MODEL)
        self.cycle()
        batched = [r for r in self.broker.requests if 'inputs' in r['content']]
        self.assertTrue(batched)
        self.assertTrue(all(len(r['content']['inputs']) <= 2 for r in batched))
        self.assertTrue(all(r['model_requirements']['target_model']['model'] == 'bge-m3:latest' for r in batched))
        self.assertTrue(all('json_schema' not in r['output'] for r in batched), '2.12 ya no lo exige')
        self.cycle()
        status = self.index.status()
        self.assertEqual(status['notes_indexed'], status['notes_published'])
        self.assertEqual(status['jobs_pending'], 0)
        with closing(self.runtime.database.connect()) as connection:
            fragments = connection.execute('SELECT COUNT(*) FROM note_fragments').fetchone()[0]
            vectors = connection.execute(
                "SELECT COUNT(*), MIN(digest) FROM fragment_embeddings WHERE model_key = ?", (MODEL.key,)
            ).fetchone()
        self.assertEqual(vectors[0], fragments)
        self.assertEqual(vectors[1], 'abc', 'el digest del modelo queda con el índice')

    def test_broker_without_batches_gets_one_text_per_task(self):
        self.publish('sola', '# A\n\nTexto.\n')
        self.index.capabilities = lambda: {'embedding_batch_max': None}
        self.index.set_model(MODEL)
        self.cycle()
        self.assertTrue(self.broker.requests)
        self.assertTrue(all('prompt' in r['content'] and 'inputs' not in r['content'] for r in self.broker.requests))

    def test_retrieval_finds_the_note_by_meaning_without_shared_words(self):
        mcp, _fillers = self.seed()
        self.index.set_model(MODEL)
        self.cycle(2)
        created = self.retrieve('¿Cómo funciona el protocolo de integración?')
        self.assertEqual(created.status_code, 202)
        self.cycle()
        question = self.broker.requests[-1]
        self.assertEqual(question['priority'], 1, 'la pregunta pasa delante del indexado')
        done = self.client.get('retrievals/' + created.json()['retrieval_id'],
                               headers={'Authorization': 'Bearer ' + TOKEN})
        self.assertEqual(done.status_code, 200)
        body = done.json()
        self.assertEqual(body['method'], 'hybrid')
        self.assertFalse(body['degraded'])
        self.assertEqual(body['documents'][0]['document_id'], mcp.note_id)
        self.assertEqual(body['unindexed_document_ids'], [])
        self.assertLess(len(body['documents']), 13, 'las notas que no tratan el tema quedan fuera')

    def test_exact_name_is_found_by_words_and_common_words_are_ignored(self):
        mcp, _fillers = self.seed()
        created = self.retrieve('Explícame cómo usar MCP de número')
        # Sin modelo elegido: solo palabras, la respuesta es inmediata y nada cuenta como indexado.
        body = created.json()
        self.assertEqual(created.status_code, 200)
        self.assertEqual(body['method'], 'lexical')
        self.assertTrue(body['degraded'])
        self.assertEqual([d['document_id'] for d in body['documents']], [mcp.note_id],
                         '«número» sale en casi todas las notas y no distingue nada')
        self.assertEqual(len(body['unindexed_document_ids']), 12)

    def test_a_rare_word_in_an_unrelated_note_does_not_bring_it_in(self):
        mcp, _fillers = self.seed()
        unrelated = self.publish('nota_zafiro', '# Cocina\n\nUna receta de cocina al horno con sal zafiro.\n')
        self.index.set_model(MODEL)
        self.cycle(2)
        created = self.retrieve('¿Cómo funciona el protocolo zafiro?')
        self.cycle()
        body = self.client.get('retrievals/' + created.json()['retrieval_id'],
                               headers={'Authorization': 'Bearer ' + TOKEN}).json()
        found = [document['document_id'] for document in body['documents']]
        self.assertEqual(found[0], mcp.note_id)
        self.assertNotIn(unrelated.note_id, found, '«zafiro» es raro, pero esa nota habla de cocina')

    def test_too_long_input_is_split_and_reindexed_without_losing_text(self):
        self.publish('larga', '# A\n\nPrimera mitad del texto. Segunda mitad del texto.\n')
        self.index.set_model(MODEL)
        self.index.refresh_fragments()
        self.index.schedule_jobs()
        with closing(self.runtime.database.connect()) as connection:
            before = ' '.join(row[0] for row in connection.execute('SELECT text FROM note_fragments')).split()
        asyncio.run(self.processor._dispatch('index_jobs', 'job_id'))
        self.broker.failures['task-1'] = {'code': 'EMBEDDING_INPUT_TOO_LONG', 'message': 'no cabe',
                                          'retryable': False, 'details': {'index': 0}}
        asyncio.run(self.processor._poll_jobs())
        with closing(self.runtime.database.connect()) as connection:
            texts = [row[0] for row in connection.execute('SELECT text FROM note_fragments ORDER BY ordinal')]
        self.assertEqual(len(texts), 2)
        self.assertEqual(' '.join(texts).split(), before)
        self.cycle(2)
        self.assertEqual(self.index.status()['notes_indexed'], 1)

    def test_changing_the_model_discards_vectors_of_the_previous_one(self):
        self.publish('una', '# A\n\nTexto.\n')
        self.index.set_model(MODEL)
        self.cycle(2)
        self.index.set_model(EmbeddingModel('ollama', 'local', 'qwen3-embedding:8b'))
        with closing(self.runtime.database.connect()) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM fragment_embeddings').fetchone()[0], 0)
        self.assertEqual(self.index.status()['notes_indexed'], 0)

    def test_only_local_embedding_models_are_offered(self):
        with self.runtime.database.transaction() as connection:
            for name, deployment, capability in (('bge-m3:latest', 'local', 'embedding'),
                                                 ('nvidia/embed', 'api', 'embedding'),
                                                 ('gemma', 'local', 'chat')):
                connection.execute(
                    'INSERT INTO model_catalog(name, provider, status, capabilities_json, discovered_at) '
                    'VALUES (?, ?, ?, ?, ?)',
                    (name, 'ollama', 'available', json.dumps({'deployment': deployment, 'status': 'available',
                                                              'capabilities': [capability]}), '2026-10-21'),
                )
        self.assertEqual(self.index.available_models(), [MODEL])


class BrokerContract212Tests(unittest.TestCase):
    def test_embedding_lane_task_with_vectors_is_valid(self):
        payload = {'task_id': 't', 'status': 'completed', 'kind': 'embedding', 'created_at': 'a', 'updated_at': 'b',
                   'progress': {'phase': 'completed'}, 'result': {'embeddings': [[1.0, 0.0], [0.0, 1.0]]},
                   'error': None}
        self.assertIs(validate_task_status_response(payload, 't'), payload)
        payload['result'] = {'embeddings': [[1.0, 0.0], [1.0]]}
        with self.assertRaises(BrokerContractError):
            validate_task_status_response(payload, 't')

    def test_quorum_failure_without_message_keeps_its_real_cause(self):
        # Respuesta literal del Broker 2.12 (21-oct, síntesis de «El Quant que Se Pasa al
        # Discrecional»): sin `message` ni `retryable`, KO la daba por error de contrato.
        error = {'code': 'CONSENSUS_QUORUM_NOT_REACHED', 'completed': 0, 'required': 2, 'skipped_proposers': [
            {'model': 'lfm2:24b', 'code': 'PROMPT_ECHOED', 'message': 'devolvió su propio prompt'},
            {'model': 'nemotron-3.5-lightning:30b', 'code': 'INVALID_PROVIDER_RESPONSE',
             'message': 'el razonamiento agotó max_output_tokens'}]}
        payload = {'task_id': 't', 'status': 'failed', 'kind': 'inference', 'execution_strategy': 'auto',
                   'created_at': 'a', 'updated_at': 'b', 'progress': {'phase': 'failed'}, 'error': error}
        self.assertIs(validate_task_status_response(payload, 't'), payload)
        message = failure_message(error)
        self.assertIn('PROMPT_ECHOED', message)
        self.assertIn('max_output_tokens', message)
        self.assertEqual(failure_message({'code': 'X', 'message': 'texto'}), 'texto')

    def test_unknown_lane_is_accepted(self):
        payload = {'task_id': 't', 'status': 'queued', 'kind': 'futuro', 'created_at': 'a', 'updated_at': 'b',
                   'progress': {'phase': 'queued'}}
        self.assertIs(validate_task_status_response(payload, 't'), payload)

    def test_inputs_are_exclusive_with_prompt(self):
        request = PromptsMixin.embedding_batch_request('r-00000001', ['a', 'b'], target=MODEL.target(), priority=1)
        validate_create_task_request(request)
        request['content']['prompt'] = 'x'
        with self.assertRaises(BrokerContractError):
            validate_create_task_request(request)

    def test_capabilities_expose_batch_and_lane(self):
        normalized = normalize_capabilities_response({'embedding_batch_max': 64,
                                                      'embedding_lane': {'max_parallel': 1, 'batch_max': 64}})
        self.assertEqual(normalized['embedding_batch_max'], 64)
        self.assertEqual(normalized['embedding_lane'], {'max_parallel': 1, 'batch_max': 64})
        self.assertIsNone(normalize_capabilities_response({})['embedding_batch_max'])


class ExtractionRobustnessTests(unittest.TestCase):
    tearDown = phase_six.PhaseSixSemanticMaintenanceTests.tearDown
    publish = phase_six.PhaseSixSemanticMaintenanceTests.publish

    def setUp(self):
        phase_six.PhaseSixSemanticMaintenanceTests.setUp(self)

    def test_segment_identifier_in_a_date_is_dropped_not_fatal(self):
        fields = _validated_fields({'note_segment': 'N1', 'source_segments': [], 'claim_type': 'HECHO',
                                'volatility': 'LOW', 'entities': [], 'observed_at': 'S6',
                                'source_date': '2026-10-20'}, 0)
        self.assertIsNone(fields['observed_at'])
        self.assertEqual(fields['source_date'], '2026-10-20')

    def test_transient_database_error_leaves_the_job_for_the_next_cycle(self):
        note = self.publish('nota', '# A\n\nProducto X dispone de la versión 2.0.\n')
        job_id = self.runtime.semantic_maintenance.schedule_extraction(note.note_id)
        with self.runtime.database.transaction() as connection:
            connection.execute("UPDATE semantic_jobs SET status = 'QUEUED', broker_task_id = 't' WHERE job_id = ?",
                               (job_id,))

        class Broker:
            async def get_task(self, *_args, **_kwargs):
                return {'status': 'completed', 'result': {'assistant_content': '{"claims": []}'}}

        processor = SemanticBrokerProcessor(self.runtime.semantic_repository, self.runtime.semantic_maintenance,
                                            Broker())
        with patch.object(self.runtime.semantic_maintenance, 'process_job_result',
                          side_effect=sqlite3.OperationalError('disk I/O error')):
            asyncio.run(processor.poll_once())
        job = self.runtime.semantic_repository.extraction_jobs(note.note_id)[-1]
        self.assertNotEqual(job.status, 'ERROR', 'un fallo pasajero del disco no es definitivo')
        asyncio.run(processor.poll_once())
        self.assertEqual(self.runtime.semantic_repository.extraction_jobs(note.note_id)[-1].status, 'SUCCESS')


if __name__ == '__main__':
    unittest.main()
