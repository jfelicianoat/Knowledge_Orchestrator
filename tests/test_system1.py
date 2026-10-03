from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import httpx

from knowledge_orchestrator.config import BrokerSettings
from knowledge_orchestrator.domain.broker_contracts import normalize_capabilities_response
from knowledge_orchestrator.domain.system1 import validate_judgment, validate_judgment_request
from knowledge_orchestrator.integrations.broker_client import BrokerClient, PermanentBrokerError, TransientBrokerError
from knowledge_orchestrator.services.prompting import estimate_tokens
from knowledge_orchestrator.services.system1 import RAG_RUBRIC, System1Service
from knowledge_orchestrator.services.system1_settings import System1Settings, load_system1_settings


def judgment(request, decision, confidence=0.99, *, accepted=True, provider='ollama_system1', fallback=False):
    domain = [False, True] if request['decision_type'] == 'binary' else request.get('options') or list(
        range(len(request['rubric'])))
    return {'use_case': request['use_case'], 'accepted': accepted,
            'decision': decision if accepted else None, 'confidence': confidence if accepted else None,
            'confidence_is_calibrated': False,
            'alternatives': [{'value': value, 'confidence': (1 - confidence) / (len(domain) - 1)}
                             for value in domain if value != decision] if accepted else [],
            'provider': provider, 'model': 'fixture-model', 'latency_ms': 1.0, 'fallback_used': fallback,
            'reason_code': None if accepted else 'LOW_CONFIDENCE', 'attempts': []}


class FakeJudge:
    def __init__(self, decisions=None, *, error=None, confidence=0.99, reject_at=None, fallback=False):
        self.decisions = decisions or {}
        self.error = error
        self.confidence = confidence
        self.reject_at = reject_at
        self.fallback = fallback
        self.requests = []

    async def judge(self, request, *, timeout_seconds=75.0):
        self.requests.append(request)
        if self.error:
            raise self.error
        identity = request['input'].get('segment_id') or request['input']['metadata']['claim_id']
        value = self.decisions.get(identity, 0 if request['decision_type'] == 'score' else 'substantive')
        decision, confidence = value if isinstance(value, tuple) else (value, self.confidence)
        return judgment(request, decision, confidence, accepted=len(self.requests) != self.reject_at,
                        provider='laya_mcp' if self.fallback else 'ollama_system1', fallback=self.fallback)


def candidates(count=12):
    return [{'claim_id': i, 'statement': f'Contenido {i}', 'knowledge_state': 'CURRENT',
             'evidence': [{'quote': 'Evidencia exacta del resultado.' if i == 10 else 'Contexto superficial. ' * 5,
                           'span_start': i * 100, 'span_end': i * 100 + 90}],
             'sources': [{'capture_id': f'source_{i}'}]} for i in range(1, count + 1)]


def transcript_fixture():
    return ''.join(line.ljust(145, '.') + '\n' for line in (
        '[00:00] La explicación técnica describe las relaciones entre variables.',
        '[00:10] Patrocinio sin contenido factual: visita nuestra tienda.',
        '[00:20] Suscríbete, comparte el vídeo y activa la campana.',
        '[00:30] El experimento midió 42 unidades; esta afirmación es contrastable.',
        '[00:40] Segmento ambiguo que debe conservarse.'))


class System1ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_authenticated_sync_score_zero_and_independent_timeout(self):
        seen = []
        def handler(request):
            seen.append(request)
            if request.url.path.endswith('capabilities'):
                return httpx.Response(200, json={'system1_judgments': True})
            return httpx.Response(200, json=judgment(json.loads(request.content), 0.0))
        client = BrokerClient(BrokerSettings(base_url='http://broker.test', admin_token='fixture-secret'),
                              transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(client.close)
        await client.capabilities()
        request = {'use_case': 'rag_chunk_relevance', 'input': {'chunk': 'texto'}, 'decision_type': 'score',
                   'rubric': RAG_RUBRIC, 'instructions': 'Evalúa.', 'cloud_allowed': False}
        result = await client.judge(request, timeout_seconds=75)
        self.assertTrue(result['accepted'])
        self.assertEqual(result['decision'], 0)
        self.assertEqual(seen[-1].url.path, '/api/v1/system1/judge')
        self.assertEqual(seen[-1].headers['X-Admin-Token'], 'fixture-secret')
        self.assertEqual(seen[-1].extensions['timeout']['read'], 75)
        self.assertNotIn('idempotency_key', json.loads(seen[-1].content))

    async def test_old_or_disabled_broker_does_not_receive_judgments(self):
        client = BrokerClient(BrokerSettings(), transport=httpx.MockTransport(
            lambda _: self.fail('No debe enviarse HTTP')))
        self.addAsyncCleanup(client.close)
        with self.assertRaises(PermanentBrokerError):
            await client.judge({'use_case': 'case', 'input': {'x': 1}, 'decision_type': 'binary'})
        for value in (None, 1, 'true', False):
            self.assertFalse(normalize_capabilities_response({'system1_judgments': value})['system1_judgments'])

    async def test_http_200_rejected_and_accepted_false_decision_are_distinct(self):
        request = {'use_case': 'case', 'input': {'x': 1}, 'decision_type': 'binary'}
        for accepted in (True, False):
            response = judgment(request, False, accepted=accepted)
            self.assertEqual(validate_judgment(response, request)['accepted'], accepted)
            self.assertIs(response['decision'], False if accepted else None)

    async def test_invalid_response_and_transport_failure_do_not_retry(self):
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(200, json={'accepted': True, 'decision': 0, 'confidence': 0.99})
        client = BrokerClient(BrokerSettings(), transport=httpx.MockTransport(handler))
        client._capabilities = {'system1_judgments': True}
        self.addAsyncCleanup(client.close)
        with self.assertRaises(PermanentBrokerError):
            await client.judge({'use_case': 'case', 'input': {'x': 1}, 'decision_type': 'binary'})
        self.assertEqual(len(calls), 1)

    def test_ordinal_domain_and_extra_fields_are_strict(self):
        request = {'use_case': 'case', 'input': {'x': 1}, 'decision_type': 'score', 'rubric': RAG_RUBRIC}
        for decision in (True, -1, 0.8, 11, float('nan')):
            with self.subTest(decision=decision), self.assertRaises(ValueError):
                validate_judgment(judgment(request, decision), request)
        with self.assertRaises(ValueError):
            validate_judgment_request({**request, 'risk': {}})


class System1RagTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_evidence_outweighs_vector_similarity_and_reduces_context(self):
        original = candidates()
        broker = FakeJudge({1: 1, 10: 10, 11: 8})
        service = System1Service(broker, System1Settings(rag_enabled=True, max_chunks=4))
        result = await service.rerank('¿Cuál fue el resultado exacto?', original)
        self.assertEqual([c['claim_id'] for c in result.items], [10, 11])
        self.assertIs(result.items[0], original[9])
        self.assertLess(result.audit['estimated_tokens_after'], result.audit['estimated_tokens_before'])
        self.assertTrue(all(r['cloud_allowed'] is False for r in broker.requests))
        self.assertTrue(all('chunk' in r['input'] for r in broker.requests))
        self.assertFalse(result.audit['fallback'])

    async def test_all_low_scores_keep_original_minimum_and_confidence_is_not_relevance(self):
        original = candidates()
        result = await System1Service(FakeJudge(), System1Settings(rag_enabled=True)).rerank('pregunta', original)
        self.assertEqual(result.items, original[:2])
        self.assertEqual(result.audit['decisions'][0]['relevance'], 0)
        self.assertEqual(result.audit['decisions'][0]['confidence'], 0.99)

    async def test_uncertain_band_and_budget(self):
        original = candidates(6)
        service = System1Service(FakeJudge({1: 10, 2: 7, 3: 6}),
                                 System1Settings(rag_enabled=True, min_chunks=1, max_chunks=2, context_tokens=300))
        result = await service.rerank('pregunta', original)
        self.assertEqual(len(result.items), 2)
        self.assertLessEqual(estimate_tokens(json.dumps(result.items, ensure_ascii=False)), 300)
        self.assertEqual(result.audit['decisions'][1]['reason'], 'UNCERTAIN')

    async def test_failures_low_confidence_and_calibration_restore_original(self):
        original = candidates()
        configurations = [
            (FakeJudge(error=TransientBrokerError('offline')), System1Settings(rag_enabled=True)),
            (FakeJudge(reject_at=2), System1Settings(rag_enabled=True)),
            (FakeJudge(confidence=0.80), System1Settings(rag_enabled=True)),
            (FakeJudge(), System1Settings(rag_enabled=True, require_calibrated=True)),
            (FakeJudge({10: 10}), System1Settings(rag_enabled=True, context_tokens=1)),
        ]
        for broker, settings in configurations:
            with self.subTest(settings=settings):
                result = await System1Service(broker, settings).rerank('pregunta', original)
                self.assertEqual(result.items, original)
                self.assertTrue(result.audit['fallback'])

    async def test_disabled_shadow_and_provider_fallback(self):
        original = candidates()
        broker = FakeJudge({10: 10}, fallback=True)
        disabled = await System1Service(broker, System1Settings()).rerank('pregunta', original)
        self.assertEqual(disabled.items, original)
        self.assertEqual(broker.requests, [])
        shadow = await System1Service(broker, System1Settings(rag_enabled=True, shadow_mode=True)).rerank(
            'pregunta', original)
        self.assertEqual(shadow.items, original)
        self.assertEqual(shadow.audit['proposed_claim_ids'][0], 10)
        active = await System1Service(broker, System1Settings(rag_enabled=True)).rerank('pregunta', original)
        self.assertFalse(active.audit['fallback'])
        self.assertTrue(active.audit['decisions'][0]['fallback_used'])


class System1TranscriptTests(unittest.IsolatedAsyncioTestCase):
    def service(self, **kwargs):
        broker = FakeJudge({'S1': 'substantive', 'S2': 'promotion', 'S3': 'filler', 'S4': 'claim',
                            'S5': ('filler', 0.88)})
        return System1Service(broker, System1Settings(transcript_enabled=True, segment_tokens=40, **kwargs))

    async def test_technical_claim_and_ambiguous_retained_promotion_and_subscription_removed(self):
        text = transcript_fixture()
        service = self.service()
        result = await service.filter_transcript(text, source_id='video', purpose='summary')
        self.assertEqual([s['segment_id'] for s in result.items], ['S1', 'S4', 'S5'])
        for segment in service.segments(text):
            self.assertEqual(segment['text'], text[segment['start']:segment['end']])
        self.assertEqual(''.join(s['text'] for s in service.segments(text)), text)
        self.assertNotIn('Patrocinio', result.text)
        self.assertIn('[00:30]', result.text)
        self.assertIn('ambiguo', result.text)
        self.assertLess(result.audit['estimated_tokens_after'], result.audit['estimated_tokens_before'])
        self.assertNotIn('Patrocinio', json.dumps(result.audit))

    async def test_research_retains_adjacent_claim_context(self):
        result = await self.service().filter_transcript(transcript_fixture(), source_id='video', purpose='research')
        self.assertEqual([s['segment_id'] for s in result.items], ['S1', 'S3', 'S4', 'S5'])
        self.assertEqual(result.audit['decisions'][2]['reason'], 'CLAIM_CONTEXT')

    async def test_rejected_halfway_or_offline_restores_full_original(self):
        text = transcript_fixture()
        for broker in (FakeJudge(error=TransientBrokerError('offline')), FakeJudge(reject_at=3)):
            service = System1Service(broker, System1Settings(transcript_enabled=True, segment_tokens=40))
            result = await service.filter_transcript(text, source_id='video')
            self.assertEqual(result.text, text)
            self.assertTrue(result.audit['fallback'])
            self.assertEqual(result.audit['final_segments'], 5)
            self.assertTrue(all(d['kept'] for d in result.audit['decisions']))

    async def test_all_noise_and_segment_limit_do_not_empty_context(self):
        text = transcript_fixture()
        broker = FakeJudge({f'S{i}': 'filler' for i in range(1, 6)})
        service = System1Service(broker, System1Settings(transcript_enabled=True, segment_tokens=40))
        result = await service.filter_transcript(text, source_id='video')
        self.assertEqual(result.text, text)
        self.assertEqual(result.audit['reason_code'], 'EMPTY_CONTEXT')
        limited = await self.service(max_segments=2).filter_transcript(text, source_id='video')
        self.assertEqual(limited.text, text)
        self.assertEqual(limited.audit['reason_code'], 'SEGMENT_LIMIT')

    async def test_disabled_and_shadow_keep_exact_original(self):
        text = transcript_fixture()
        service = self.service(shadow_mode=True)
        shadow = await service.filter_transcript(text, source_id='video')
        self.assertEqual(shadow.text, text)
        self.assertTrue(all(d['kept'] for d in shadow.audit['decisions']))
        disabled = System1Service(FakeJudge(), System1Settings())
        self.assertEqual((await disabled.filter_transcript(text, source_id='video')).text, text)
        self.assertEqual(disabled.client.requests, [])

    async def test_stage_timeout_preserves_original_and_cancels_call(self):
        cancelled = asyncio.Event()
        class Slow:
            async def judge(self, *args, **kwargs):
                try:
                    await asyncio.sleep(20)
                finally:
                    cancelled.set()
        service = System1Service(Slow(), System1Settings(transcript_enabled=True, stage_timeout_seconds=0.01))
        text = transcript_fixture()
        result = await service.filter_transcript(text, source_id='video')
        self.assertEqual(result.text, text)
        self.assertEqual(result.audit['reason_code'], 'STAGE_TIMEOUT')
        self.assertTrue(cancelled.is_set())


class System1SettingsTests(unittest.TestCase):
    def test_json_and_environment_overrides_and_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            (state / 'system1.json').write_text('{"rag_enabled":true,"min_chunks":3}', encoding='utf-8')
            with patch.dict('os.environ', {'KO_SYSTEM1_SHADOW_MODE': 'true', 'KO_SYSTEM1_MAX_CHUNKS': '5'}):
                settings = load_system1_settings(state)
                self.assertTrue(settings.rag_enabled)
                self.assertTrue(settings.shadow_mode)
                self.assertEqual((settings.min_chunks, settings.max_chunks), (3, 5))
        for kwargs in ({'min_chunks': 0}, {'min_chunks': 10, 'max_chunks': 2}, {'relevance_keep': float('nan')},
                       {'transcript_enabled': 'true'}, {'segment_tokens': 0}, {'adjacent_segments': -1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                replace(System1Settings(), **kwargs)
