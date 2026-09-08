"""Texto de auditoría: versión histórica y decisión actual siempre diferenciadas."""
from __future__ import annotations

STATES = {'PENDING_COMPARISON': 'Por comparar', 'PENDING_REVIEW': 'Pendiente de revisión',
          'APPLYING': 'Publicación en curso', 'APPLIED': 'Publicada', 'REJECTED': 'Descartada',
          'CONFLICT': 'Conflicto', 'ERROR': 'Error'}


def audit_text(record: dict) -> dict[str, str]:
    candidate, selected = record['candidate'], record['selected']
    snapshot = record['snapshot'] or {}
    summary = f"Propuesta {candidate['candidate_id']} · " + STATES.get(candidate['status'], candidate['status'])
    summary += (f" · Mostrando revisión {selected['revision']} de propuesta" if selected
                else ' · Sin evaluación versionada conservada')
    summary += '. Consulta histórica; no autoriza cambios ni acredita vigencia actual.'
    evidence = [snapshot.get('rationale') or 'No hay justificación guardada para esta revisión.']
    for index, entry in enumerate(snapshot.get('evidence', [])):
        source = entry.get('source') or {}
        monitoring = source.get('monitoring') or {}
        evidence.append(('Evidencia anterior' if index == 0 else 'Evidencia nueva')
            + f"\n{source.get('title', 'Sin título')} · Captura {source.get('capture_id', 'sin dato')}"
            + f"\n{source.get('source_url', 'Documento local o URL no disponible')}"
            + f"\nConfianza configurada: {monitoring.get('trust_level', 'sin dato')}"
            + f"\n{entry.get('quote', 'Sin cita guardada')}")
        if monitoring:
            evidence.append(f"Fuente vigilada {monitoring.get('monitored_source_id', 'sin dato')} · "
                            f"revisión {monitoring.get('source_revision', 'sin dato')}\n"
                            f"Cambio detectado: {monitoring.get('source_change_id', 'sin dato')}")
    evidence.append('Análisis que constaba al guardar esta revisión')
    jobs = snapshot.get('analysis_jobs', [])
    if not jobs:
        evidence.append('No hay tareas de análisis registradas en este snapshot. No se infiere un modelo.')
    for job in jobs:
        evidence.append(('Extracción' if job['kind'] == 'EXTRACT' else 'Comparación')
            + f"\nTarea: {job['job_id']}\nTarea del Broker: {job.get('broker_task_id') or 'No registrada'}"
            + '\nModelos reportados: ' + (', '.join(job.get('reported_models', [])) or 'No informados'))
    evidence.append('La confianza de fuente y los modelos reportados no prueban veracidad factual.')
    decision = [f"Registro creado: {candidate['created_at']}",
                f"Revisión actual de propuesta: {candidate['proposal_revision']}",
                f"Decisión registrada por: {candidate['reviewed_by'] or 'Sin decisión de publicación'}",
                f"Fecha de decisión: {candidate['reviewed_at'] or 'Sin fecha'}",
                f"Fecha de publicación: {candidate['applied_at'] or 'Sin publicación terminada'}",
                f"Nota destino: {candidate['target_note_id']} · Afirmación anterior: {candidate['target_claim_id']}",
                f"Afirmación nueva: {candidate['new_claim_id']} · Sucesor: "
                + str(candidate['applied_successor_id'] or 'No publicado')]
    if selected:
        decision.insert(0, f"Revisión consultada: {selected['revision']} · Autor: {selected['actor']} · "
                           f"Registrada: {selected['created_at']}\n\nDecisión/publicación de la propuesta actual")
    policy = record['policy']
    if policy:
        decision.append(f"Política que autorizó la intención: {policy['policy_id']} · "
                        f"revisión {policy['policy_revision']}\n"
                        f"Ejecución: {policy['run_id']}\nSimulación de ejecución: {policy['simulation_id']}\n"
                        f"Autorización por: {policy['authorized_by'] or 'Sin dato'} · "
                        f"{policy['authorized_at'] or 'Sin fecha'}\n"
                        'Simulación revisada al autorizar: '
                        + (policy['reviewed_simulation_id'] or 'Sin vínculo registrado') + '\n'
                        'Condiciones y recibo disponibles en Servicios → Automatizaciones → Políticas y decisiones.')
    else:
        decision.append('No consta una intención de publicación por política para esta propuesta. '
                        'Las simulaciones sin aplicación se consultan en el historial de políticas.')
    if record['batch']:
        batch = record['batch']
        decision.append(f"Lote humano: {batch['batch_id']} · Confirmado por {batch['owner']}\n"
                        f"Confirmación: {batch['confirmed_at'] or 'Pendiente'}\n"
                        'Recibo disponible en Revisión → Lotes anteriores.')
    if record['previous_note']:
        previous = record['previous_note']
        decision.append(f"Versión anterior de nota conservada: {previous['revision']} · {previous['created_at']}\n"
                        'Contenido disponible en Histórico de decisiones → Ver versión anterior.')
    if record['reversion']:
        reversion = record['reversion']
        decision.append(('Esta publicación fue revertida.' if reversion['status'] == 'APPLIED' else
                         'Hay una reversión en curso para esta publicación.')
                        + f"\nReversión: {reversion['reversion_id']} · Actor: {reversion['owner']}\n"
                        'Consulta el recibo en Revisión → Publicaciones y reversión.')
    return {'summary': summary, 'before': snapshot.get('before') or 'Sin evidencia anterior guardada.',
            'proposed': snapshot.get('proposed') or 'Sin reemplazo documental en esta revisión.',
            'evidence': '\n\n'.join(evidence), 'decision': '\n\n'.join(decision)}
