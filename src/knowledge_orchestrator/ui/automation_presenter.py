"""Texto y conversión de formularios para decisiones de gobernanza."""
from __future__ import annotations

from knowledge_orchestrator.domain.automation import AutomationPolicyConfig

NUMERIC_FIELDS = {
    'min_source_trust': 'Confianza mínima de fuente (0–100)',
    'min_confidence': 'Confianza mínima de comparación (0–1)',
    'max_claims_per_task': 'Máximo de afirmaciones por propuesta',
    'max_notes_per_task': 'Máximo de notas por propuesta',
    'max_tasks_per_run': 'Máximo de propuestas por ejecución',
    'max_tasks_per_day': 'Máximo de propuestas por día (UTC)',
}
CHOICES = {
    'source_kinds': {'web': 'Web', 'rss': 'RSS / Atom'},
    'source_roles': {'official_documentation': 'Documentación oficial', 'official_repository': 'Repositorio oficial',
                     'official_blog': 'Blog oficial', 'secondary': 'Fuente secundaria', 'generic': 'Web genérica'},
    'relations': {'SUPERSEDES': 'Sustituye una afirmación anterior', 'EXTENDS': 'Amplía conocimiento existente'},
}
BLOCKERS = {
    'MANUAL_LOCK': 'Bloqueo manual: necesita revisión humana.',
    'POLICY_DISABLED': 'La política no está autorizada.', 'AUTOMATION_PAUSED': 'La autoaprobación está pausada.',
    'SOURCE_OUTSIDE_POLICY': 'La fuente está fuera del ámbito autorizado.',
    'SOURCE_DISABLED': 'La vigilancia de esta fuente está desactivada.',
    'SOURCE_REVISION_CHANGED': 'La configuración de la fuente cambió después de capturar la evidencia.',
    'SOURCE_TRUST_BELOW_POLICY': 'La fuente no alcanza la confianza mínima configurada.',
    'SOURCE_ROLE_NOT_ALLOWED': 'El tipo de procedencia no está permitido.',
    'SOURCE_KIND_NOT_ALLOWED': 'El conector de la fuente no está permitido.',
    'MONITORED_PROVENANCE_REQUIRED': 'Falta procedencia verificable de una fuente vigilada.',
    'CLAIM_TYPE_NOT_ALLOWED': 'El tipo de afirmación no está permitido.',
    'CLAIM_NOT_CURRENT': 'Hay afirmaciones que ya no están vigentes.',
    'CLAIM_LIMIT': 'Supera el máximo de afirmaciones por propuesta.',
    'NOTE_LIMIT': 'Supera el máximo de notas por propuesta.',
    'RUN_TASK_LIMIT': 'Supera el cupo de esta ejecución.', 'DAILY_TASK_LIMIT': 'Se agotó el cupo diario.',
    'DEPENDENT_NOTE_UPDATES': 'Hay cambios que dependen de la misma nota; revísalos por separado.',
    'ASSESSMENT_MISSING': 'Falta un análisis de impacto vigente.',
    'PROPOSAL_CHANGED': 'La propuesta cambió; vuelve a simular.',
    'RELATION_NOT_ALLOWED': 'La relación requiere revisión humana.',
    'CONFIDENCE_BELOW_POLICY': 'La comparación no alcanza la confianza mínima.',
}


def config_from_fields(values: dict[str, str], choices: dict[str, list[str]],
                        source_ids: set[int]) -> AutomationPolicyConfig:
    claim_types = tuple(value.strip() for value in values['claim_types'].split(',') if value.strip())
    converted: dict = {'name': values['name'].strip(), 'source_ids': tuple(source_ids),
                       'claim_types': claim_types,
                       **choices}
    for field, label in NUMERIC_FIELDS.items():
        try:
            converted[field] = (float(values[field].replace(',', '.')) if field == 'min_confidence'
                                else int(values[field]))
        except ValueError as error:
            raise ValueError(f'{label}: introduce un número válido.') from error
    return AutomationPolicyConfig(**converted)


def simulation_selection_matches(simulation: dict | None, selection: list[dict] | None) -> bool:
    if selection is None:
        return True
    if simulation is None:
        return False
    actual = [(item['candidate_id'], item['revision']) for item in simulation['plan']['items']]
    expected = [(item['candidate_id'], item['expected_revision']) for item in selection]
    return sorted(actual) == sorted(expected)


def simulation_matches(policy: dict | None, simulation: dict | None, control: dict, *, dirty: bool,
                       selection: list[dict] | None = None) -> bool:
    return bool(not dirty and policy and simulation and simulation_selection_matches(simulation, selection) and (
        policy['policy_id'], policy['revision'], policy['state_revision'], control.get('revision')) == (
        simulation['policy_id'], simulation['policy_revision'], simulation['policy_state_revision'],
        simulation['control_revision']))


def reasons(codes: list[str]) -> str:
    return ' '.join(BLOCKERS.get(code, 'No cumple una condición de aplicación; revisa la propuesta.') for code in codes)


def config_summary(config: dict) -> str:
    groups = [f"{config['name']} · {len(config['source_ids'])} fuentes seleccionadas",
              f"Tipos de afirmación: {', '.join(config['claim_types'])}."]
    for field, labels in CHOICES.items():
        groups.append(', '.join(labels.get(value, value) for value in config[field]) + '.')
    groups.extend(f'{label}: {config[field]}' for field, label in NUMERIC_FIELDS.items())
    return '\n'.join(groups)
