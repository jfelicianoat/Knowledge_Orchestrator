# Campos de propuesta y trazabilidad

Inspección del 8 de septiembre de 2026. Complementa `Acceptance_Evidence.md` sin
declarar completada la aceptación global. Las rutas siguientes parten de `src/knowledge_orchestrator/`.
Se distinguen datos persistidos, pruebas locales y verificaciones reales pendientes.

## Diecinueve campos exigidos a una propuesta

El productor es `services/maintenance_assessment.py::assess_proposal`; el contenedor
versionado se guarda en `maintenance_proposal_versions` por `record_comparison`.
`SemanticMaintenanceService.proposal_detail` entrega el snapshot y sus versiones.

| Requisito | Evidencia actual | Alcance |
|---|---|---|
| Descripción del cambio | `description`, relación y texto antes/propuesto | Descripción determinista de la acción y contenido concreto separado |
| Claims nuevos | `new_claim`, `planned_counts.new_claims` | Evidencia nueva; el sucesor documental se crea al publicar |
| Claims existentes afectados | `existing_claim`, `affected_claim_ids` | Incluye spans solapados que bloquean aplicación |
| Entidades afectadas | `entities`, entidades de ambos claims | Etiquetas; los vínculos normalizados se consultan en Knowledge Core |
| Evidencia anterior | `before`, `evidence[0]` | Cita conservada y procedencia |
| Evidencia nueva | `evidence[1]`, `new_claim` | Cita original; reemplazo exige correspondencia con la evidencia |
| Fuente | `evidence[*].source` | Captura y procedencia vigilada si existe |
| Trust de fuente | `source_trust`, `source.monitoring.trust_level` | Puede faltar en fuentes locales; no prueba veracidad |
| Relación semántica | `relation` | Contrato validado; no texto libre de control |
| Explicación | `rationale` | Justificación resumida; no cadena privada de razonamiento |
| Impacto esperado | `impact`, `expected_effect`, `planned_counts` | Separación de estimación y transformación prevista |
| Notas afectadas | `affected_note_ids` | Nota destino; evidencia conserva sus notas de origen |
| Claims afectados | `affected_claim_ids` | Selección concreta y guardas de solapamiento |
| Patch/transformación | `patch`, `history_strategy` | Puede ser nulo si la relación no requiere publicación |
| Confianza | `confidence` y riesgo explícito | No constituye autorización ni prueba factual |
| Riesgos/incertidumbres | `risks`, `blockers` | Contradicciones, confianza y bloqueos separados |
| Autoaprobación | `autoapproval`, contexto `automation_review`, simulación | Evaluación explícita por política; snapshot no autoriza |
| Fecha | `versions[*].created_at`; candidato conserva creación/revisión/aplicación | Fecha del registro inmutable, no fecha inventada en el snapshot |
| Identificadores de auditoría | candidato/revisión, claims/notas/capturas, `analysis_jobs` | Tareas del Broker y modelos reportados cuando existen |

La prueba `test_phase_six_semantic_maintenance.py::test_publication_automatically_runs_durable_extraction_and_comparison_jobs`
ejecuta el procesador con un Broker simulado, comprueba campos, ambas citas/capturas,
fecha de versión, tres tareas y modelos reportados, y publica por decisión humana
conservando el snapshot y la nota anterior. La confianza vigilada y las contradicciones
se verifican en `test_phase_twelve_knowledge_maintenance.py`; el contexto de política
y la conservación byte a byte de snapshots antiguos, en `test_proposal_policy_review.py`.
Esto no acredita extracción ni comparación de un modelo real.

## Doce categorías de observabilidad

| Categoría requerida | Registro estructurado inspeccionado | Productor |
|---|---|---|
| Comprobaciones de fuente | `source_checks`, `SOURCE_CHECK_*` | `repositories/source_repository.py` |
| Cambios detectados | `source_changes` con check, fuente/revisión, hashes y procedencia; `SOURCE_CHECK_CHANGED` | Mismo repositorio |
| Ingestas | `SOURCE_CHANGE_DELIVERED` enlaza recibo; `CAPTURE_STAGED` enlaza captura | Repositorios de fuente/captura |
| Análisis | `semantic_jobs`, `SEMANTIC_JOB_STATE_CHANGED` | `semantic_repository/trabajos.py` |
| Propuestas | `MAINTENANCE_CANDIDATE_STATE_CHANGED`, `MAINTENANCE_PROPOSAL_REVISED` | `semantic_repository/candidatos.py` |
| Decisiones humanas | versiones/actor, rechazo, intención APPLYING, `REVIEW_BATCH_CONFIRMED` | Candidatos y lotes |
| Decisiones automáticas | `AUTOMATION_APPLICATION_RESERVED`, `AUTOMATION_ITEM_FINISHED` | Guardas y ejecuciones |
| Política aplicada | reserva con política/revisión, simulación y ejecución | `automation_guards.py`, `automation_run_repository.py` |
| Revisión | `maintenance_proposal_versions`, `note_revisions`, versiones/decisiones de políticas | Repositorios respectivos |
| Estado de claims | `claim_state_history`, `CLAIM_STATE_CHANGED`, `CLAIM_STATE_REVIEWED` | `knowledge_repository.py`, `maintenance_states.py` |
| Publicación | `PUBLICATION_PREPARED`, `CAPTURE_COMPLETED`, `SEMANTIC_UPDATE_APPLIED` | Publicación y candidatos |
| Errores | fallos de checks/entrega, análisis ERROR, conflictos de propuesta, fallos/recibos de ejecución | Repositorios respectivos |

Los nuevos eventos semánticos solo se emiten cuando hay una transición efectiva.
Creación repetida, sondeo sin cambio, terminal ya registrado y recuperación repetida
no generan duplicados. READY → SUBMITTING → READY sí registra un reintento real.
SUCCESS se registra después de integrar el resultado, no al recibir el HTTP del Broker.
Una decisión APPLYING queda registrada antes de reemplazar la nota; APPLIED acredita
la terminación y conserva actor, revisión, lote/ejecución y sucesor.

Evento y transición usan la misma transacción SQLite. Si insertar el evento falla,
se deshacen tanto el cambio de estado como el contador/intención de esa transacción.
Los eventos nuevos no copian prompts, resultados, documentos, URLs de estado ni mensajes
remotos de error. Los motivos de conflicto se limitan a códigos locales conocidos;
otros se representan como `UNSPECIFIED`. El detalle original sigue en su registro de
dominio. Esta protección no acredita una auditoría completa de saneamiento de todos
los eventos históricos y rutas de error anteriores.

El decimotercer incremento corrige dos fronteras anteriores concretas:

- `operations.py`: cabeceras/asignaciones, JSON textual anidado, URL y token Broker
  configurado en memoria. El ZIP solo toma líneas completas; no altera logs anteriores.
  Las pruebas de operaciones comprueban ausencia de secretos ficticios en log/trace/ZIP
  y conservación de códigos, estado e identificadores de petición.
- `domain/contracts.py`: errores YAML con posición y causa sin snippets ni traceback
  encadenado. La prueba de ingestión comprueba evento/sidecar sin el contenido privado
  y original byte a byte en cuarentena. El documento rechazado no se elimina.

Estas protecciones no anonimizan texto libre arbitrario ni reescriben mensajes remotos
persistidos previamente. El ZIP deja explícita esta limitación; no se afirma que cualquier
log antiguo carezca de datos privados.

El decimocuarto incremento evita duplicar texto de avisos, URLs de citas sin respaldo
y mensajes de fallo de consenso en los eventos de workflows. Los eventos enlazan la
tarea y conservan contadores/código permitido; sus respuestas y metadata originales
continúan disponibles en el registro de tarea. `test_workflow_audit_privacy.py` comprueba
privacidad de estos eventos, decisión de fallback sin cambios, terminal idempotente y
rollback completo ante fallo de auditoría. No acredita saneamiento de las respuestas
remotas persistidas ni modifica registros históricos.

El decimosexto incremento añade saneamiento compartido en `redaction.py` y la frontera
de errores del cliente Broker. Cubre credencial de petición/configuración vigente,
respuestas tardías después de rotación y traceback visible de errores de conexión.
`test_broker_error_privacy.py` verifica persistencia en tareas y trabajos semánticos,
conservación de códigos/estado y reintentos. No modifica resultados de negocio ni datos
históricos; no constituye anonimización universal de texto privado.

## Diez preguntas de reconstrucción

| Pregunta | Cadena verificable |
|---|---|
| Quién o qué inició la actualización | check/fuente y captura; tarea de comparación; actor de versión; intención humana/lote o ejecución de política |
| Qué fuente la provocó | candidato → new_claim → source_capture_id → source_changes/api_ingestions → fuente/revisión/check |
| Qué evidencia existía | snapshot `evidence`, `evidence_links`, hashes de patch y revisión de nota |
| Qué modelo/tarea participó | `analysis_jobs` con job_id/broker_task_id/reported_models; `semantic_jobs` guarda resultado |
| Qué propuesta se generó | candidato y revisión de `maintenance_proposal_versions` |
| Qué política fue evaluada | ejecución → simulation_id → política/revisión y plan inmutable |
| Quién aprobó o si fue automática | reviewed_by y review_batch_id/automation_run_id; intención y evento de publicación |
| Qué cambió | patch/diff del candidato y snapshot de propuesta; sucesor y estados de claims |
| Qué versión anterior existía | `note_revisions`, histórico temporal y evidencia anterior |
| Cuándo ocurrió | fechas de checks, versiones, eventos, intención y aplicación |

`test_semantic_audit.py` verifica siete escenarios: transiciones/reintentos/recuperación,
fallos terminales, rollback de auditoría de trabajos, creación/conflicto idempotentes,
publicación por política con enlaces exactos, conflictos de otras propuestas tras
sustitución y rollback de intención cuando falla auditoría. Las pruebas de recuperación
y publicación anteriores cubren conservación de histórico y resultados parciales.

## Límites que siguen abiertos

- Los eventos nuevos no se reconstruyen retrospectivamente para trabajos antiguos;
  las filas y snapshots previos conservan la evidencia disponible, sin inventar fechas.
- Los modelos son los reportados por el Broker. Si no informó modelo o el análisis se
  introdujo directamente, no se inventa uno ni se afirma que hubo una ejecución real.
- El duodécimo incremento añade **Ver trazabilidad** a Revisión y Propuestas/Histórico
  de decisiones, con versiones, comparación, fuentes, tareas/modelos y atribución de
  publicación/reversión. Sus lectores/controladores y textos se prueban localmente;
  la prueba nativa se amplía pero el render sigue pendiente por Tcl/Tk. Esto no acredita
  todavía el recorrido visual integral de todos los entregables de la aplicación.
- El inventario de entregables y criterios globales está en `Delivery_Acceptance_Audit.md`;
  distingue requisitos locales, parciales y dependientes de prueba real. Este documento
  de campos/categorías/reconstrucción no sustituye los gates pendientes del inventario.
- Persisten las limitaciones de Tcl/Tk, red y flujo real Plugin → Broker → Obsidian
  documentadas en `CURRENT_STATE.md`.
