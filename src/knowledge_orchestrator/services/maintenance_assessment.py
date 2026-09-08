"""Impacto verificable y contexto que se congela junto con cada revisión del diff."""
from __future__ import annotations

import json
from contextlib import closing
from dataclasses import asdict

from knowledge_orchestrator.domain.semantic_models import ComparisonDecision, KnowledgeClaim, UpdateCandidate
from knowledge_orchestrator.repositories.semantic_repository import SemanticRepository
from knowledge_orchestrator.services.provenance import source_provenance

RELATIONS = {'SUPERSEDES': 'Sustituir la formulación anterior con evidencia posterior.',
             'EXTENDS': 'Ampliar la formulación con la evidencia nueva.',
             'CONTRADICTS': 'Resolver una contradicción mediante revisión humana.',
             'SUPPORTS': 'Registrar una evidencia concordante sin modificar la nota.',
             'UNRELATED': 'No se propone modificación: las evidencias no están relacionadas.',
             'UNCERTAIN': 'Revisar una relación que no pudo establecerse con suficiente claridad.'}


def assess_proposal(repository: SemanticRepository, candidate: UpdateCandidate, decision: ComparisonDecision,
                    target: KnowledgeClaim, new_claim: KnowledgeClaim, patch_json: str | None) -> dict:
    sources = [source_provenance(repository.database, claim.source_capture_id) for claim in (target, new_claim)]
    patch = json.loads(patch_json) if patch_json else None
    risks = ['SOURCE_TRUST_IS_NOT_FACTUAL_PROOF', 'MODEL_CONFIDENCE_IS_NOT_FACTUAL_PROOF']
    blockers = []
    if target.manual_lock or new_claim.manual_lock:
        blockers.append('MANUAL_LOCK')
    if decision.relation == 'CONTRADICTS':
        risks.append('CONFLICTING_EVIDENCE_REQUIRES_HUMAN_REVIEW')
        trust = [source.get('monitoring', {}).get('trust_level') for source in sources]
        if all(isinstance(value, int) and value >= 80 for value in trust):
            risks.append('HIGH_TRUST_SOURCES_DISAGREE')
        if all(isinstance(value, int) for value in trust) and trust[1] < trust[0]:
            risks.append('LOWER_TRUST_SOURCE_DISAGREES')
    if decision.relation == 'UNCERTAIN':
        risks.append('SEMANTIC_RELATION_UNCERTAIN')
    if any('monitoring' not in source for source in sources):
        risks.append('SOURCE_TRUST_NOT_CONFIGURED')
    affected_claims = [target.claim_id]
    with closing(repository.database.connect(readonly=True)) as connection:
        if patch:
            overlaps = connection.execute(
                "SELECT claim_id,manual_lock FROM knowledge_claims WHERE note_id=? AND status='ACTIVE' "
                'AND claim_id<>? AND span_start<? AND span_end>?',
                (target.note_id, target.claim_id, patch['end'], patch['start'])).fetchall()
            affected_claims += [row['claim_id'] for row in overlaps]
            if overlaps:
                blockers.append('OVERLAPPING_CLAIMS')
            if any(row['manual_lock'] for row in overlaps):
                blockers.append('MANUAL_LOCK')
        jobs = [dict(row) for row in connection.execute(
            'SELECT job_id,broker_task_id,kind,result_json FROM semantic_jobs WHERE candidate_id=? OR '
            "(kind='EXTRACT' AND note_id IN (?,?)) ORDER BY created_at", (candidate.candidate_id,
                                                                        target.note_id, new_claim.note_id))]
    for job in jobs:
        result = json.loads(job.pop('result_json') or '{}') or {}
        reported = result.get('models_used', [])
        if not isinstance(reported, list):
            reported = []
        reported = [*reported, result.get('model_used')]
        job['reported_models'] = sorted({item['model'][:200] for item in reported
                                         if isinstance(item, dict) and isinstance(item.get('model'), str)})
    if patch is None:
        blockers.append('NO_DOCUMENT_PATCH')
    old_quote, new_quote = (repository.evidence_quote(claim.claim_id) for claim in (target, new_claim))
    return {
        'candidate_id': candidate.candidate_id, 'description': RELATIONS[decision.relation],
        'relation': decision.relation, 'confidence': decision.confidence, 'impact': decision.impact,
        'rationale': decision.rationale, 'before': old_quote, 'proposed': decision.replacement_text,
        'existing_claim': asdict(target), 'new_claim': asdict(new_claim),
        'entities': sorted(set(target.entities) | set(new_claim.entities)),
        'evidence': [{'claim_id': target.claim_id, 'quote': old_quote, 'source': sources[0]},
                     {'claim_id': new_claim.claim_id, 'quote': new_quote, 'source': sources[1]}],
        'source_trust': [source.get('monitoring', {}).get('trust_level') for source in sources],
        'affected_claim_ids': affected_claims, 'affected_note_ids': [target.note_id],
        'planned_counts': {'existing_claims': len(affected_claims), 'new_claims': 1 if patch else 0,
                           'notes': 1 if patch else 0},
        'expected_effect': 'Se conserva la versión anterior y se registra un sucesor con evidencia original.'
                           if patch else 'La nota permanece igual; el análisis queda registrado.',
        'history_strategy': patch.get('history_strategy', 'revision_snapshot') if patch else 'unchanged',
        'patch': patch, 'risks': sorted(set(risks)), 'blockers': sorted(set(blockers)), 'analysis_jobs': jobs,
        'autoapproval': {'eligible': False, 'policy_evaluated': False, 'publication_authorized': False,
                         'reasons': ['POLICY_EVALUATION_REQUIRED', *sorted(set(blockers))]},
    }
