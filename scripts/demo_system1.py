"""Dos demos reproducibles de política, con juicios controlados y sin llamadas de inferencia."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from knowledge_orchestrator.integrations.broker_client import TransientBrokerError
from knowledge_orchestrator.services.system1 import System1Service
from knowledge_orchestrator.services.system1_settings import System1Settings


class FixtureJudge:
    def __init__(self, labels: dict, *, offline: bool = False) -> None:
        self.labels = labels
        self.offline = offline

    async def judge(self, request: dict, *, timeout_seconds: float) -> dict:
        if self.offline:
            raise TransientBrokerError('Broker offline en la demostración')
        identity = request['input'].get('segment_id') or request['input']['metadata']['claim_id']
        value = self.labels.get(identity, 0)
        decision, confidence = value if isinstance(value, tuple) else (value, 0.99)
        domain = request.get('options') or list(range(len(request['rubric'])))
        alternatives = [{'value': other, 'confidence': (1 - confidence) / (len(domain) - 1)}
                        for other in domain if other != decision]
        return {'use_case': request['use_case'], 'accepted': True, 'decision': decision, 'confidence': confidence,
                'confidence_is_calibrated': False, 'alternatives': alternatives,
                'provider': 'ollama_system1', 'model': 'controlled_fixture', 'latency_ms': 0,
                'fallback_used': False, 'reason_code': None,
                'attempts': [{'provider': 'ollama_system1', 'model': 'controlled_fixture', 'latency_ms': 0,
                              'reason_code': None, 'decision': decision, 'confidence': confidence,
                              'alternatives': alternatives, 'score_source': 'native',
                              'tokens_input': None, 'tokens_output': None}]}


def rag_candidates() -> list[dict]:
    return [{'claim_id': index, 'knowledge_state': 'CURRENT',
             'evidence': [{'quote': ('La medición de referencia obtuvo exactamente 42 unidades.' if index == 10 else
                                     'El método de medida empleó un instrumento calibrado.' if index == 11 else
                                     'Este documento menciona medidas y experimentos de un tema diferente.'),
                           'span_start': 0, 'span_end': 80}],
             'sources': [{'capture_id': f'document_{index}'}], 'retrieval_score': round(1 - index * 0.02, 2)}
            for index in range(1, 13)]


def transcript() -> str:
    return '\n'.join([
        '[00:00] La explicación técnica muestra cómo una variable de entrada determina '
        'la salida del sistema analizado.',
        '[00:10] Este espacio está patrocinado: visita la tienda y utiliza nuestro código de descuento al comprar.',
        '[00:20] Si te gusta el canal, suscríbete, comparte este vídeo con tus amigos y activa las notificaciones.',
        '[00:30] El experimento publicado obtuvo 42 unidades en la medición, '
        'una afirmación factual que debemos conservar.',
        '[00:40] Este pasaje resulta ambiguo para el clasificador y se conserva completo, '
        'para no perder información útil.',
    ]) + '\n'


async def demonstrate() -> dict:
    items = rag_candidates()
    settings = System1Settings(rag_enabled=True, transcript_enabled=True, segment_tokens=40)
    rag = await System1Service(FixtureJudge({10: 10, 11: 8}), settings).rerank(
        '¿Qué resultado obtuvo el experimento de referencia?', items)
    relevant = {10, 11}
    selected = {c['claim_id'] for c in rag.items}
    scores = {'recall': len(selected & relevant) / len(relevant),
              'precision': len(selected & relevant) / len(selected),
              'interpretation': 'Mide la política con etiquetas y juicios simulados; no mide un modelo real.'}
    text = transcript()
    labels = {'S1': 'substantive', 'S2': 'promotion', 'S3': 'filler', 'S4': 'claim', 'S5': ('filler', 0.88)}
    service = System1Service(FixtureJudge(labels), settings)
    summary = await service.filter_transcript(text, source_id='fixture_video', purpose='summary')
    research = await service.filter_transcript(text, source_id='fixture_video', purpose='research')
    offline = System1Service(FixtureJudge({}, offline=True), settings)
    rag_fallback = await offline.rerank('¿Resultado?', items)
    transcript_fallback = await offline.filter_transcript(text, source_id='fixture_video')
    rag_scenarios = [rag.audit, rag_fallback.audit]
    transcript_scenarios = [summary.audit, research.audit, transcript_fallback.audit]
    return {'mode': 'controlled_policy_demo', 'real_inference': False,
            'rag': {'candidate_ids': [c['claim_id'] for c in items], 'selected_claim_ids': sorted(selected),
                    'audit': rag.audit, 'labelled_policy_check': scores},
            'transcript': {'original_text': text, 'summary_text': summary.text, 'summary_audit': summary.audit,
                           'research_text': research.text, 'research_audit': research.audit},
            'fallback': {'rag_restores_original': rag_fallback.items == items,
                         'transcript_restores_original': transcript_fallback.text == text,
                         'rag_audit': rag_fallback.audit, 'transcript_audit': transcript_fallback.audit},
            'scenario_metrics': {'rag_fallback_ratio': sum(a['fallback'] for a in rag_scenarios) / len(rag_scenarios),
                                 'rag_scenarios': len(rag_scenarios),
                                 'transcript_fallback_ratio': sum(a['fallback'] for a in transcript_scenarios) /
                                                              len(transcript_scenarios),
                                 'transcript_scenarios': len(transcript_scenarios),
                                 'interpretation': 'Tasas solo de los escenarios simulados de esta demo.'}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = asyncio.run(demonstrate())
    if args.output:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    rag = result['rag']['audit']
    tr = result['transcript']['summary_audit']
    print(f"RAG: {rag['initial_chunks']} -> {rag['final_chunks']} candidatos; "
          f"tokens estimados {rag['estimated_tokens_before']} -> {rag['estimated_tokens_after']}")
    print(f"Transcripción: {tr['initial_segments']} -> {tr['final_segments']} segmentos; "
          f"tokens estimados {tr['estimated_tokens_before']} -> {tr['estimated_tokens_after']}")
    print('Juicios simulados: no se ha medido calidad, latencia ni consumo de modelos reales.')
