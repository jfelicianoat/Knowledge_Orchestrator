# Inventario de entregas y aceptación global

Inspección del 8 de septiembre de 2026 contra la especificación de fases 9–14.
Este inventario conserva el alcance completo. **No acredita el cierre del proyecto.**
Se contrastaron contratos, productores y aserciones de las pruebas citadas con el
árbol de trabajo; la mera existencia de un archivo no se considera una verificación.

## Cómo interpretar la evidencia

- **L — VERIFICADO localmente:** comportamiento cubierto por pruebas con SQLite y
  archivos temporales; los Brokers/conectores sustituidos no acreditan inferencia ni red real.
- **P — PARCIAL:** implementación y parte de su comportamiento comprobadas, pero falta
  evidencia material del alcance completo. No equivale a requisito cerrado.
- **R — REQUIERE PRUEBA REAL:** la evidencia depende de render, entorno externo o recorrido
  completo y no se obtuvo. La implementación puede existir.

Referencias abreviadas a pruebas bajo `tests/`:

| Clave | Archivo |
|---|---|
| T9 | `test_phase_nine_knowledge_core.py` |
| T10 | `test_phase_ten_knowledge_api.py` |
| T11 | `test_phase_eleven_source_monitoring.py` |
| T12 | `test_phase_twelve_knowledge_maintenance.py` |
| T13 | `test_phase_thirteen_operations_ui.py` |
| TB | `test_review_batches.py` |
| TG | `test_automation_governance.py` |
| TE | `test_automation_execution.py` |
| TS | `test_automation_scheduler.py` |
| TR | `test_maintenance_reversion.py` |
| TO | `test_operations_status.py` |
| TA | `test_semantic_audit.py` y `test_proposal_audit_view.py` |

Las rutas de producción siguientes parten de `src/knowledge_orchestrator/`.
La batería vigente y los comandos de calidad están en [CURRENT_STATE.md](CURRENT_STATE.md).

## Entregables explícitos de cada fase

| ID | Fase 9: requisito | Fuente actual y evidencia | Estado |
|---|---|---|---|
| 9.1 | Entity | `domain/knowledge.py::Entity`; T9 enlaces e idempotencia de entidades | L |
| 9.2 | Evolución de claims | `migrations/012_knowledge_core.sql`, `knowledge_claims`; T9 migración legacy conserva IDs, spans y evidencia | L |
| 9.3 | Relaciones temporales | `superseded_by`, consulta inversa `supersedes` en `KnowledgeAccess.claim_payload`; T9 sucesión de predecesor/sucesor | L |
| 9.4 | Seis estados | `KnowledgeState`; T9 revisiones, exclusión de no vigentes y prohibición de reactivar histórico | L |
| 9.5 | Migraciones | 012 aditiva y triggers; T9 inicialización repetida, datos legacy y foreign keys | L |
| 9.6 | Servicios de dominio | `services/knowledge.py`, `repositories/knowledge_repository.py`; T9 decisiones con actor, motivo y revisión | L |
| 9.7 | Current/history | `KnowledgeRepository.state_filter`; T9 sucesión y T10 lectura API separada | L |
| 9.8 | Reconciliación | `KnowledgeService.reconcile`; T9 edición externa/archivo ausente sin sobrescribir ni cambiar claim bloqueado | L |
| 9.9 | Tests | T9: diez escenarios, más regresión vigente; no migración sobre la bóveda real | L |

| ID | Fase 10: requisito | Fuente actual y evidencia | Estado |
|---|---|---|---|
| 10.1 | API versionada | `api/application.py::KnowledgeApi`, prefijo `/api/v1`; T10 rutas y métodos | L |
| 10.2 | Contratos | `api/contracts.py`; T10 JSON duplicado, tipos, IDs y límites | L |
| 10.3 | Schemas | `api/response_schemas.py`, `api/openapi.py`; T10 OpenAPI y pruebas API de revisión/gobernanza/reversión | L |
| 10.4 | Autenticación/autorización | `api/auth.py`; T10 scopes, identidad de consumidor, token inválido/duplicado; TO listener real loopback | L |
| 10.5 | Lectura | `services/knowledge_access.py`; T10 documentos, revisiones, entidades, claims y conflicto documental | L |
| 10.6 | Búsqueda | `KnowledgeAccess.search`; T10 filtros FTS y estado vigente | L |
| 10.7 | Semantic search | `KnowledgeAccess.semantic_search`; T10 modelo/dimensión y exclusión de histórico. Recibe un vector, no texto para generar embeddings | L |
| 10.8 | Query fundamentado | `services/knowledge_query.py`; T10 selección de citas, insuficiencia, IDs inventados, propiedad y obsolescencia | P: modelo real pendiente |
| 10.9 | Ingestión controlada | `services/api_ingestion.py`; T10 misma identidad, entrega/reinicio y uso de la ingesta existente | L |
| 10.10 | Tests contractuales | T10 y pruebas API de gobernanza/reversión/lotes; incluyen solicitudes inválidas y permisos | L |
| 10.11 | OpenAPI | `api/openapi.py::specification`, `GET /openapi.json`; T10 y contratos API posteriores | L |

| ID | Fase 11: requisito | Fuente actual y evidencia | Estado |
|---|---|---|---|
| 11.1 | Source/Connector | `domain/monitoring.py::SourceConfig`, `source_connectors.py::Connector`; protocolo y conectores inyectables | L para Web/RSS actuales |
| 11.2 | Scheduler | `worker/source_worker.py`, `SourceRepository.lease_due`; T11 dos fuentes concurrentes y lease vencido | L |
| 11.3 | Deduplicación | `source_changes`, `source_items`; T11 A→B→A y entrega repetida conservan identidades correctas | L |
| 11.4 | Hash/change detection | `SourceItem.content_hash`, validadores HTTP; T11 hash, 304 y normalización | L |
| 11.5 | Uno/dos conectores | `WebConnector`, `RssConnector` (RSS/Atom); T11 HTML, código, feed y no descarga de artículos | P: descarga real pendiente |
| 11.6 | Errores recuperables | `SourceMonitoringService.check/deliver_ready`; T11 caída entre recibo/enlace y trabajador antiguo rechazado | L |
| 11.7 | Backoff | `repositories/source_repository.py`; T11 espera creciente y fuente/ingesta fallida sin bloquear otra | L |
| 11.8 | Auditoría | `source_checks`, `source_changes`, revisiones; T11 procedencia original y edición concurrente | L |
| 11.9 | Configuración visual mínima | `ui/dashboard/fuentes.py`; prueba nativa T11 implementada pero omitida por Tcl/Tk | R |
| 11.10 | Tests | T11 incluye atomicidad, errores, red protegida, normalización y recuperación | L salvo render/red real |

El protocolo admite nuevas implementaciones por composición. `SourceConfig.kind` y
sus contratos/UI admiten hoy `web` y `rss`: un conector nuevo requiere ampliar ese
registro y sus contratos, no solo añadir una clase. GitHub releases, APIs vigiladas,
búsqueda web programada y otras bóvedas son extensiones futuras permitidas por la
especificación; no se presentan como implementadas.

| ID | Fase 12: requisito | Fuente actual y evidencia | Estado |
|---|---|---|---|
| 12.1 | Análisis de impacto | `services/maintenance_assessment.py`; T12 counts y snapshots; prueba del procesador de fase 6 verifica campos completos | L; inferencia real pendiente |
| 12.2 | Relaciones semánticas | `services/semantic_maintenance`, `domain/semantic_models.py`; T12 SUPERSEDES/contradicciones y citas | L |
| 12.3 | Reasoning resumido | `rationale` en propuesta versionada; T12 edición conserva justificación anterior y actor nuevo | L para contrato; calidad real pendiente |
| 12.4 | Evidencia | extracción/cita exacta, hashes de origen y destino; T12 rechazo de afirmación inventada y fuente cambiada | L |
| 12.5 | Propuestas | `maintenance_proposal_versions`; T12 edición optimista, regeneración legacy e inmutabilidad | L |
| 12.6 | Riesgos | assessment con blockers/risks/trust; T12 contradicción de fuentes y confianza no autorizante | L |
| 12.7 | Actualización Obsidian | `maintenance_layout.py` y publicación semántica; T12 secciones actuales/históricas o snapshot, texto no afectado intacto | L; editor real concurrente pendiente |
| 12.8 | CURRENT/HISTORICAL | `maintenance_states.py`; T9/T12 sucesión y proyección en nota destino | L |
| 12.9 | Conflictos | guardas de aplicación/evidencia; T12 hash antes/después de intención y escritura temporal | P: ventana check/replace del filesystem |
| 12.10 | Reindexado | `maintenance_projection.py`, FTS/vector; T12 offsets, fuente original, embeddings y reextracción sin resucitar histórico | L |
| 12.11 | Casos normales/negativos | T12: evidencia inventada, solapamientos, edición concurrente, fuentes contradictorias, API y recuperación | L |

| ID | Fase 13: requisito | Fuente actual y evidencia | Estado |
|---|---|---|---|
| 13.1 | Dashboard | `ui/dashboard/inicio.py`, `_build_pipeline/_poll_pipeline` en operaciones; `OperationsSnapshots.counts` | P: datos/controladores locales, render pendiente |
| 13.2 | Knowledge explorer | `ui/dashboard/conocimiento.py`; T13 current/history, filtros y reconciliación | P |
| 13.3 | Sources | `ui/dashboard/fuentes.py`; T11 configuración y acciones nativas pendientes | R |
| 13.4 | Changes | `ui/dashboard/operaciones.py`; T13 novedad→captura→nota→propuesta | P |
| 13.5 | Review | `ui/dashboard/revision.py`, `proposal_audit_dialog.py`; TA versión fija, antes/propuesto y decisión | P |
| 13.6 | Bulk actions | `review_batch_dialog.py`, servicio de lotes; TB preview, parcial por tarea, selección y recuperación | P: ejecución local, widgets pendientes |
| 13.7 | History | Operaciones/Histórico, versiones de nota y diálogo de trazabilidad; T13/TA revisión anterior y snapshot fijo | P |
| 13.8 | API/status | `ui/dashboard/servicios.py`, `OperationsStatusService`; TO estado real del listener, consumidores y actividad sin cuerpos | P |
| 13.9 | Automation | `ui/automation_panel.py`, `reversion_panel.py`; pruebas de formularios, selección, simulación/autorización y reversión | P |
| 13.10 | Filtros | T13 y pruebas UI de políticas: estado, etapa, texto, paginación y borrador/selección estable | P |
| 13.11 | Flujos visuales | Seis botones navegables del pipeline; T13 cadena de IDs; evaluación visual integral ausente | R |
| 13.12 | Estados vacíos | T13 `test_empty_snapshot_and_filter_validation` y `test_flow_empty_stages_and_invalid_filter`; textos de vistas | P |
| 13.13 | Errores claros | TO listener detenido/puerto ocupado; TA lectura fallida y reintento exacto; pruebas UI de navegación fallida | P: legibilidad/render pendientes |

La decisión explícita de conservar Tkinter, sus límites, alternativas, coste/riesgo y
compatibilidad con servicios está en [Phase_13_Knowledge_Operations_UI.md](Phase_13_Knowledge_Operations_UI.md).
La navegación se organiza en Inicio, documentos/biblioteca, Conocimiento, Fuentes,
Operaciones, Revisión, Servicios y configuración. Histórico y automatizaciones tienen
entradas dentro de estos flujos. No se ha migrado el framework ni se acredita UX por inspección de código.

| ID | Fase 14: requisito | Fuente actual y evidencia | Estado |
|---|---|---|---|
| 14.1 | Políticas versionadas | `AutomationPolicyConfig`, `automation_repository.py`; TG edición revoca autorización e historial inmutable | L |
| 14.2 | Simulación/dry-run | `automation_simulation.py`; TG no publica ni reserva, conserva evidencia; pruebas API de hash/revisión/propietario | L |
| 14.3 | Elegibilidad | `automation_guards.py`; TG/TE fuente, relación, umbral, conflictos, evidencia y revisiones revalidados | L |
| 14.4 | Ejecución automática | `automation_execution.py`, `automation_scheduler.py`; TE/TS ejecución autorizada, leases, cursor, recibos y recuperación | L |
| 14.5 | Logs | `operations.py`, eventos de repositorios; pruebas de saneamiento y privacidad de auditoría de workflows | P: otras rutas/texto remoto requieren revisión |
| 14.6 | Auditoría | matrices de propuesta y eventos transaccionales; TA actor/revisión/lote/política, simulación revisada y ejecución diferenciadas | L para registros nuevos cubiertos |
| 14.7 | Límites | config por tarea/ejecución/día y reservas; TE cuotas concurrentes y rollback transaccional, TS planes grandes | L |
| 14.8 | Kill switch | control versionado, pausa por defecto; TG/TE/TS pausa durante simulación, antes de intención y recuperación | L |
| 14.9 | manual_lock | guardas de intención y reversión; TE bloqueo añadido después de simular, TR bloqueo después de preview | L |
| 14.10 | Rollback cuando posible | `maintenance_reversion.py`, migración 021; TR snapshot exacto, revisión posterior/dependencias bloquean, recuperación | L para reversión conservadora; render pendiente |
| 14.11 | Tests agresivos | TG/TE/TS/TR, API y fuente adversaria: concurrencia, corrupción, permisos, fallos transaccionales y reinicio | L en escenarios controlados |

## Contratos y campos transversales

Los diez objetivos de producto originales se vinculan así, sin reducirlos a las
capacidades ya verificadas:

| Objetivo | Entregas/criterios que lo prueban | Alcance pendiente |
|---|---|---|
| 1. Obsidian legible y editable | 12.7, reconciliación, criterio 9 | Editor real concurrente y recorrido externo |
| 2. Representación estructurada | 9.1–9.8 y contrato de claim | Límite de fechas/procedencia explícito |
| 3. Estados explícitos | 9.4/9.7, criterio 1 | Comprobado localmente |
| 4. Consumo mediante API | 10.1–10.11 y tabla de rutas | Query con Broker real |
| 5. Escrituras gobernadas | 10.9, revisión/lotes, 14.1–14.4 | Interacción visual real |
| 6. Vigilancia externa | 11.1–11.10 | Descarga y pantalla reales |
| 7. Análisis IA de impacto | 12.1–12.4 | Modelo real y fuente adversaria |
| 8. Propuesta antes de modificación | 12.5 y guardas, criterio 4 | Calidad legible con modelo real |
| 9. Tres mecanismos de aprobación | Individual, masiva y política en tablas anteriores | Checkpoint visual integral |
| 10. Centro de operaciones visual | 13.1–13.13, criterio 15 | Render y navegación real |

El ciclo de doce pasos tiene estos registros/productores: SOURCE CHECK
(`source_checks`), CHANGE DETECTED (`source_changes`), INGEST (`api_ingestions` y
`captures`), CLAIM EXTRACTION (`semantic_jobs` EXTRACT), CLAIM MATCHING (candidatos
creados desde extracción), SEMANTIC COMPARISON (trabajo y resultado de comparación),
IMPACT ANALYSIS (assessment versionado), UPDATE PROPOSAL (candidato/revisión),
REVIEW/POLICY (decisión/lote/simulación autorizada), APPLY (intención/publicación),
REINDEX (proyección/FTS/vector) y PUBLISH/API (nota y acceso de conocimiento).
La prueba del procesador de fase 6, T11/T12 y TA verifican tramos locales; esto no
equivale a una ejecución externa completa de los doce pasos.

Indicadores y navegación: Inicio muestra proceso/errores/revisión/publicación y
salud del Broker; el pipeline añade vigentes/históricos/en revisión/contradicciones
y etapas. Operaciones ofrece cambios y actividad; Servicios muestra consumidores,
ejecuciones automáticas y pausa. Los contadores tienen ámbitos distintos (novedades
pendientes frente a número de fuentes) y no deben interpretarse como intercambiables.
Falta comprobar visualmente que esos ámbitos y enlaces se entienden sin consultar logs.

| Requisito explícito | Representación inspeccionada | Límite de evidencia |
|---|---|---|
| Claim: entity_id, contenido normalizado, evidencia, fuente, nota | `claim_entities`, `normalized_statement`, `evidence_links`, `source_capture_id`, `note_id`; `KnowledgeAccess.claim_payload` | Una relación n:m reemplaza la columna única; T9/T10/T12 |
| Claim: created_at, valid_from/until, status, supersedes/by, revisión | columnas y `claim_state_history`; `supersedes` es consulta inversa | Fechas operativas, no fecha factual inferida; T9 |
| Claim: provenance, manual_lock, metadata de auditoría | fuente/cita/hashes, lock, historial y candidato/proyección | No se inventan sucesores o modelos ausentes; T9/T12/TA |
| Fuente: tipo, localización, frecuencia, activación, scope, trust | `SourceConfig`; configuración versionada y API/UI | Web/RSS, scope descriptivo, trust configurado no prueba factual |
| Fuente: última comprobación, contenido/hash, estado, configuración, política de ingestión | `monitored_sources`, `source_checks/items/changes`, config `review`/`ingest` | Revisión por defecto; ingestión no equivale a aprobar conocimiento; T11 |
| Secretos de fuentes | `credential_env`, URL rechaza credenciales embebidas, `source_http.py` | Referencias de entorno; pruebas de redirección y no transmisión a host distinto |
| Diecinueve campos de propuesta | [Proposal_Audit_Evidence.md](Proposal_Audit_Evidence.md), productor `assess_proposal` | Campos y snapshots comprobados; interpretación de modelo real pendiente |
| Doce categorías de observabilidad y diez preguntas de reconstrucción | Mismo documento: check→captura→análisis→propuesta→decisión→publicación | Eventos nuevos; no reconstrucción ficticia del pasado |
| Preview masivo: tareas, claims, notas, acciones, conflictos, no elegibles | `review_batches.py` plan/counts/items y `ReviewBatchDialog`; TB preview inmutable y resultados parciales | Requiere inspección visual de todos los campos, no solo tests de datos |
| Individual: aprobar/editar/rechazar | servicio semántico, API y Revisión; T12 edición/revisión obsoleta y repetición | Acciones locales verificadas; recorrido visual pendiente |
| Masivo: seleccionadas/todas elegibles | selección explícita o snapshot sin selección, preview+confirmación y worker | TB conserva alcance original; no incluye candidatos posteriores |
| Política: fuente/tipo/trust/confianza/relación/claims/notas/ausencia de contradicciones y conflictos/tipo de cambio | `AutomationPolicyConfig` y guardas; TG/TE | Solo SUPERSEDES/EXTENDS permitidos; confianza sola nunca autoriza |
| Query: answer, claims, evidence, sources, knowledge_state, uncertainty, generated_at | `KnowledgeQueryService.answer`; `uncertainties` es el nombre público documentado | Citas exactas, máximo 24 candidatos y 60.000 caracteres; insuficiencia explícita |
| Query: current/historical/all | snapshot, filtros, revalidación/fingerprint | T10 excluye histórico por defecto e invalida resultado obsoleto |

### Rutas conceptuales de la especificación

Todas tienen prefijo `/api/v1`; registro vigente en `api/openapi.py::ROUTES` y
despacho en `KnowledgeApi.dispatch` (gobernanza/reversión en adaptadores separados).

| Rutas requeridas | Implementación/decisión |
|---|---|
| GET vaults, documents, documents/{id} | Mismos recursos; una bóveda por runtime, historial documental adicional |
| GET entities, entities/{id}, claims, claims/{id} | Mismos recursos; IDs numéricos, filtros explícitos e historial adicional |
| GET knowledge/{entity}, knowledge/{entity}/history | `{entity_id}`; current por defecto, sucesión marcada como histórica |
| GET search, POST search/semantic | FTS y vector en espacio de modelo declarado |
| POST query | Consulta durable; seguimiento con GET queries/{query_id} y propietario |
| POST sources, documents, ingestions | Fuentes configurables; documents/ingestions comparten ingesta idempotente, no publicación directa |
| GET review-tasks, review-tasks/{id}; POST approve/reject | Revisión optimista y scopes; PATCH añade edición/regeneración |
| POST review-tasks/bulk-approve | Variante deliberada: POST review-batches/preview, después POST review-batches/{batch_id}/confirm; recibo consultable por propietario |

Las decisiones y ejemplos están en [Knowledge_API.md](Knowledge_API.md).
Los endpoints originales siguen disponibles; la variante masiva separa la revisión del
plan de su autorización. No se eliminó un endpoint existente para introducirla.

## Guardas y compatibilidad

| Exigencia | Evidencia / estado |
|---|---|
| No borrar histórico ni perder provenance | T9/T12/TR conservan versiones/citas, proyecciones y sucesores; migraciones 012–021 aditivas. L |
| No sobrepasar manual_lock | T9/T12/TE/TR, guardas compartidas y reservas. L en rutas cubiertas |
| No sobrescribir base/hash diferente | T9/T12/TR detectan edición antes de intención y durante escritura. P: ventana entre último check y replace no es CAS con editor externo |
| No presentar contenido no verificado como verificado ni consenso como evidencia factual | Claims etiquetados `evidence_linked_not_independently_verified`, query con incertidumbre, assessment distingue trust/certeza. P: legibilidad visual y modelo real |
| No actualizar solo por fecha caducada | `test_temporal_authorization.py`: claim fechado sin evidencia nueva, observación posterior de texto idéntico y reemplazo inferido por fecha sin cita; política autorizada, reloj avanzado y reinicio no publican. L |
| No aplicar solo por confianza del modelo | T12 reemplazo sin cita rechazado; TG/TE exigen fuente, evidencia, relación y autorización. L |
| No masivos silenciosos sin política aprobada | TB preview/confirmación; TG/TE/TS desactivación/pausa por defecto y revisiones exactas. L |
| Documentos no pueden modificar instrucciones ni ejecutar sus órdenes | `test_untrusted_source_boundaries.py`, delimitadores y contratos estrictos; no herramientas de documento ejecutadas. P: obediencia de modelo real pendiente |
| Confirmación para lo destructivo/difícil de revertir | Lotes y reversión requieren plan y confirmación; no borrados/migración incompatible/framework nuevo. No se han activado políticas globales del usuario |
| Idempotencia y recuperación tras restart | T9/T10/T11/TB/TE/TS/TR y tests de ingestión/publicación; límites de filesystem explícitos. L local |
| Fronteras Orchestrator/Broker | Orchestrator gobierna fuentes/conocimiento/decisiones; BrokerClient entrega tareas técnicas; sin scheduling de modelos/VRAM trasladado. Inspección local; interoperabilidad real pendiente |
| Compatibilidad Broker | `test_broker_client.py`, contratos y workflows fases 3/5/6; avisos/resultados originales conservados en tarea. L contractual, R real |

## Dieciséis criterios de aceptación global

| # | Criterio original | Evidencia decisiva y lo pendiente | Estado |
|---|---|---|---|
| 1 | Vigente e histórico diferenciados | 9.3/9.4/9.7 y 10.5; T9/T10 con IDs, estados y sucesión | L |
| 2 | Ningún histórico perdido | 9.5, 12.7, 14.10; snapshots byte a byte y triggers, casos legacy/reinicio | L en escenarios verificados |
| 3 | Claims con evidencia/provenance | 12.4/12.10, contrato de claim; citas y origen de proyecciones | L |
| 4 | Propuestas explican el cambio | 12.1/12.3/12.5, diecinueve campos; calidad con modelo real pendiente | P |
| 5 | Revisión individual funciona | T12 y 13.5; falta interacción/render real | P |
| 6 | Revisión masiva funciona | TB parcial por tarea/idempotencia; falta interacción/render real | P |
| 7 | Autoaprobación gobernada | 14.1–14.4/14.7–14.9; autorización y reservas revalidadas | L |
| 8 | manual_lock inviolable | Guardas y tests 9/12/TE/TR; todas las rutas cubiertas lo respetan | L local; no afirmación universal sobre código futuro |
| 9 | Obsidian/modelo razonablemente consistentes | Reconciliación/proyección/reindexado/reversión; falta editor externo en ventana filesystem | P |
| 10 | API distingue current/history | T10 claims/search/entity_history y conflicto documental | L |
| 11 | Query fundamentado | T10 citas/IDs/insuficiencia/obsolescencia; inferencia real pendiente | P |
| 12 | Conectores se recuperan | T11/worker y entrega idempotente; red real pendiente | P |
| 13 | Workflows idempotentes | Pruebas de envío/reinicio, publicación, lotes, scheduler y reversión | L local |
| 14 | Operaciones externas reconciliables | Intenciones antes de efectos; pruebas de cortes locales. Cadena externa no ejecutada | P |
| 15 | UI permite comprender flujo sin SQLite/logs | Pipeline, explorador, comparación, versiones, decisión y servicios implementados; checkpoint visual ausente | R |
| 16 | Cambios importantes auditables | TA y matrices de auditoría; actores, evidencia, política, propuesta y versión anterior | L para registros nuevos; legado conserva evidencia disponible |

Los veinte escenarios obligatorios tienen su matriz independiente en
[Acceptance_Evidence.md](Acceptance_Evidence.md). No se sustituyen por los dieciséis
criterios anteriores ni por el número total de tests.

## Checkpoints y acciones que impiden cerrar

| Gate | Evidencia vigente | Estado |
|---|---|---|
| Fase 9 antes de continuar | Registro `Phase_9_Knowledge_Core.md`, núcleo/migración/regresión | Local superado |
| Fase 10 | Contratos y listener loopback; `Phase_10_Knowledge_API.md` | Local superado, integración externa pendiente |
| Fase 11 | Scheduler/conectores simulados/recuperación; `Phase_11_Source_Monitoring.md` | Pantalla y descarga real pendientes |
| Fase 12 | Núcleo/API/evidencia/publicación local; `Phase_12_Knowledge_Maintenance.md` | Local superado; modelo/editor real pendientes |
| Fase 13 visual y funcional | Cinco pruebas nativas omitidas por init.tcl; revisión parcial de controladores | Abierto; código no reemplaza render |
| Fase 14 | Políticas, simulación, ejecución, cuotas y reversión locales; registro por incrementos | Abierto; auditoría global/visual/externa incompleta |
| Calidad después de cambios | unittest, ruff, mypy y diff; resultado vigente en CURRENT_STATE | No implica cierre de requisitos P/R |

Acciones concretas pendientes:

1. Ejecutar las cinco pruebas nativas y recorrer las pantallas a tamaños reales,
   incluyendo comparación, lote parcial, políticas, pausa, reintento y auditoría.
   La revisión integral anterior de Servicios/políticas no terminó por cuota; las
   revisiones acotadas posteriores no la sustituyen. No insistir sin cambio del entorno.
2. Ejecutar una captura de prueba Plugin → Orchestrator → Broker → Obsidian, query con
   evidencia y fuente adversaria, con Broker/descarga reales. El último estado de red
   documentado es WinError 10013/NETWORK_DENIED antes de HTTP; no prueba token inválido.
3. Revisar la persistencia de errores remotos fuera de los eventos mínimos nuevos:
   cliente, envío, trabajos semánticos, respuestas y detalles de tareas pueden conservar
   texto libre. No se han saneado retrospectivamente datos ni logs del usuario.
4. Comprobar la convivencia con un editor externo durante el último check/replace.

La guarda de fecha sola se verifica en el decimoquinto incremento. `source_date` y
`observed_at` describen la evidencia; no autorizan sustitución. Un claim con una fecha
antigua conserva su cita y estado local sin inventar una conclusión actual sobre su
contenido. `CURRENT` sigue significando vigencia del registro local, no veracidad factual.
Estas pruebas no introducen un scheduler de caducidad ni acreditan inferencia de un modelo real.

No se requiere instalar todos los conectores futuros ni migrar el framework para
cerrar el alcance acordado. Tampoco se autoriza borrar histórico, activar políticas
globales o cambiar contratos incompatibles para facilitar las pruebas.
