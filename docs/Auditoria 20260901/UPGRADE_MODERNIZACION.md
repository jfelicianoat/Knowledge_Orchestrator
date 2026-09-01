# Resumen ejecutivo de modernización

La modernización propuesta conserva las garantías durables existentes y cambia el foco a mantenibilidad, observabilidad, delivery reproducible y evolución del runtime.

- Baseline recomendado: **Python 3.13**.
- Dependencias exactas mediante lock + SBOM.
- pytest 9, mypy 2 y ruff actual tras resolver breaking changes.
- CI con matriz y quality gates.
- Separación de UI monolítica en vistas/presenters.
- Extracción de máquinas de estado grandes desde repositorios/servicios.
- Contratos Broker versionados explícitamente y contract tests.
- Observabilidad con logging estructurado estable + métricas de operación.
- Perfil LAN y perfil hardened para comunicación Broker.
- Evidencia E2E archivada por release.

# Diferencias clave vs plan conservador

| Área | Conservador | Modernización |
|---|---|---|
| Python | 3.11 | 3.13 |
| pytest/mypy | conservar majors | pytest 9 / mypy 2 |
| Arquitectura UI | sin refactor | dividir dashboard |
| State machines | solo fixes | separar transición/validación/persistencia |
| Observabilidad | logs actuales | métricas + correlación + SLOs locales |
| Broker security | warning/config | perfiles LAN/hardened |
| CI | gate mínimo | matriz, SBOM, SCA, artifacts |
| E2E | smoke/manual | escenario de release automatizable |

# Targets recomendados (modernización) y justificación

| Componente | Target | Justificación |
|---|---|---|
| Python | 3.13.x | soporte hasta 2029-10 y fase bugfix en 2026 |
| PyYAML | 6.0.3 | release estable actual observada |
| watchdog | 6.0.0 | release estable actual observada |
| httpx | 0.28.1 | estable actual; evitar 1.0 prerelease |
| pytest | 9.1.x | tooling actual |
| ruff | 0.16.x | tooling actual |
| mypy | 2.3.x | tooling actual |
| setuptools | 84.x o versión validada actual | build reproducible |
| Broker contract | política de compatibilidad semver/tabla | eliminar literales dispersos |

# Plan por áreas (arquitectura/observabilidad/tests/CI/deps/infra)

## Arquitectura
1. Mantener `runtime.py` como composition root.
2. Dividir `ui/dashboard.py`:
   - `ui/views/home.py`
   - `ui/views/work.py`
   - `ui/views/review.py`
   - `ui/views/topics.py`
   - `ui/views/config.py`
   - presenters/view-models sin Tk para lógica de presentación.
3. Extraer de `workflow_repository.apply_status()`:
   - normalización de payload;
   - decisión de transición;
   - escritura transaccional.
4. Extraer de `ingestion.ingest()` un pipeline de pasos recuperables.
5. Reutilizar validadores pequeños para contratos Broker/Markdown.

## Observabilidad
- Mantener JSON logs.
- Campos correlacionados: `capture_id`, `workflow_id`, `task_id`, `note_id`, `attempt`.
- Métricas internas simples:
  - queue depth,
  - age oldest,
  - broker latency,
  - retry count,
  - recoveries,
  - publications,
  - semantic failures.
- Snapshot diagnóstico debe incluir métricas agregadas, nunca contenido sensible.
- Estado operacional separado: `BROKER_OFFLINE`, `AUTH_REQUIRED`, `CONTRACT_MISMATCH`, `DEGRADED`.

## Tests
- Unit tests para transiciones puras.
- Contract tests Broker 2.8/2.9.
- Integration tests SQLite+filesystem con directorios temporales.
- Tests de crash checkpoints de publicación/ingesta.
- E2E de release en entorno controlado.
- Tests property-based opcionales para nombres/contratos si el coste encaja.

## CI
- Python 3.13 principal; 3.11 temporal durante migración.
- Windows obligatorio por producto desktop.
- Linux para dominio/repositorios sin UI si aporta velocidad.
- Gates: ruff, mypy, tests, build, SBOM, SCA, secret scan.
- Artefactos de build + manifest de versiones.

## Dependencias
- Lock exacto.
- Renovación periódica automatizada.
- Política: producción minor/patch automática con tests; majors en PR dedicado.

## Infra
No hay infraestructura cloud/container declarada; no introducirla sin necesidad. La modernización debe seguir siendo apropiada para una app desktop local.

# Touchpoints

## PHASE_0 — fundación y alto riesgo

| Ruta | Símbolo/área | Cambio esperado | Riesgo | Validación |
|---|---|---|---|---|
| `pyproject.toml` | metadata/tooling | Python 3.13 + pytest9/mypy2 | High | install + gates |
| `worker/broker_worker.py` | `_refresh_capabilities` | política versionada | Medium | contract tests |
| `integrations/broker_client.py` | errores/auth | estado AUTH_REQUIRED | Medium | integration |
| `repositories/database.py` | readonly/diagnostics | URI `mode=ro` | Low | DB tests |
| `ui/dashboard.py` | clase principal | seams antes de split | High | UI snapshot tests |
| `repositories/workflow_repository.py` | `apply_status` | extraer transición | High | state tests |
| `services/ingestion.py` | `ingest` | pipeline de pasos | High | recovery tests |
| `services/publication.py` | materialización/recovery | validar filesystem boundaries | High | crash/recovery tests |
| `services/operations.py` | logging/diagnostics | métricas + redaction tests | Medium | security tests |
| CI/lock | nuevo | reproducibilidad | High | clean build |

## PLAN_POR_FASES

### Fase 0 — Fundación
- Lock/SBOM.
- CI/gates.
- Python 3.13 branch.
- Corrección Broker 2.9.
- Métricas y IDs de correlación.
- Characterization tests antes de refactors.

### Fase 1 — Upgrades mayores
- Python 3.13.
- pytest 9.
- mypy 2.
- setuptools/tooling actual.
- Mantener httpx 0.28.1 hasta que 1.0 sea estable y exista motivo para migrar.

### Fase 2 — Refactors y deuda
- Dashboard → vistas.
- State transitions puras.
- Ingestion pipeline.
- Contract validators pequeños.
- Mejor frontera de config/security.

### Fase 3 — Hardening
- Perfil hardened TLS/token.
- SCA/secret scanning.
- E2E release.
- Recovery/backup drills.
- Performance baselines de SQLite/FTS y polling.

## Inventario de símbolos para completar touchpoints

| Ruta | Símbolos principales |
|---|---|
| `src/knowledge_orchestrator/app.py` | `initialize_phase_one`, `main` |
| `src/knowledge_orchestrator/config.py` | `PipelinePaths (defaults, under, database, failed_contracts, failed_duplicates, failed_transcriptions, ensure_directories)`, `_default_broker_url`, `_default_admin_token`, `BrokerSettings` |
| `src/knowledge_orchestrator/domain/broker_contracts.py` | `BrokerContractIssue`, `BrokerContractError (__init__)`, `_fail`, `_mapping`, `_string`, `validate_create_task_request`, `validate_accepted_response`, `validate_task_status_response`, `normalize_capabilities_response`, `validate_models_response` |
| `src/knowledge_orchestrator/domain/broker_models.py` | `WorkflowStatus`, `TaskStatus`, `StepKind`, `PlannedTask`, `BrokerTaskRecord`, `WorkflowRecord` |
| `src/knowledge_orchestrator/domain/contracts.py` | `_UniqueKeySafeLoader`, `_construct_unique_mapping`, `_raise`, `_require_type`, `_optional_string`, `_valid_http_url`, `_validate_datetime`, `_validate_metadata`, `parse_capture_bytes` |
| `src/knowledge_orchestrator/domain/errors.py` | `ContractIssue (as_dict)`, `CaptureContractError (__init__)`, `FileLockedError`, `FileStabilityError`, `IngestionCancelled`, `RecoveryError` |
| `src/knowledge_orchestrator/domain/models.py` | `CaptureStatus`, `SourceOrigin`, `CaptureDocument (__post_init__, capture_id, contract_version, source_type, title)`, `CaptureRecord`, `IngestionResult`, `ApplicationEvent (__post_init__)`, `ProfileDefinition`, `TopicDefinition`, `TopicAssignment` |
| `src/knowledge_orchestrator/domain/profiles.py` | `ProfileValidationError`, `prompt_fields`, `validate_profile` |
| `src/knowledge_orchestrator/domain/publication_models.py` | `PublishableWorkflow`, `NoteRecord`, `ReprocessIntent` |
| `src/knowledge_orchestrator/domain/semantic_models.py` | `ExtractedClaim`, `KnowledgeClaim`, `UpdateCandidate`, `ComparisonDecision`, `SemanticJob` |
| `src/knowledge_orchestrator/domain/sources.py` | `infer_source_origin`, `is_prohibited_source_type`, `autonomous_sources_enabled` |
| `src/knowledge_orchestrator/domain/topics.py` | `TopicValidationError`, `normalize_search_text`, `validate_topic` |
| `src/knowledge_orchestrator/integrations/broker_client.py` | `BrokerClientError (__init__)`, `TransientBrokerError`, `PermanentBrokerError`, `BrokerClient (__init__, start, close, create_task, get_task, cancel_task, list_models, capabilities…)` |
| `src/knowledge_orchestrator/repositories/capture_repository.py` | `_path`, `_record`, `CaptureRepository (__init__, get, count, list_by_status, list_unenriched_pending, insert_staged, transition, mark_pending…)` |
| `src/knowledge_orchestrator/repositories/database.py` | `Database (__init__, connect, transaction, initialize, journal_mode)` |
| `src/knowledge_orchestrator/repositories/domain_repository.py` | `_profile`, `_topic`, `DomainRepository (__init__, get_profile, list_profiles, enabled_topic_usage_count, save_profile, get_topic, get_inbox_topic, list_topics…)` |
| `src/knowledge_orchestrator/repositories/publication_repository.py` | `_note`, `_intent`, `PublicationRepository (__init__, list_publishable, create_intent, get_note, get_workflow_for_note, fail_publication, list_notes_by_status, mark_published…)` |
| `src/knowledge_orchestrator/repositories/semantic_repository.py` | `normalize_text`, `_claim`, `_candidate`, `_job`, `SemanticRepository (__init__, note_context, add_claim, get_claim, list_claims, set_manual_lock, find_related, create_candidate…)` |
| `src/knowledge_orchestrator/repositories/workflow_repository.py` | `_task`, `_workflow`, `WorkflowRepository (__init__, list_unplanned_capture_ids, next_revision, list_resumable_workflow_ids, recover_interrupted_submissions, upgrade_legacy_ready_requests, create_workflow, insert_synthesis_task…)` |
| `src/knowledge_orchestrator/runtime.py` | `OrchestratorRuntime (recover_once, start, stop, run_forever)`, `build_runtime` |
| `src/knowledge_orchestrator/services/broker_dispatch.py` | `BrokerDispatcher (__init__, dispatch_once)`, `BrokerPoller (__init__, poll_once)` |
| `src/knowledge_orchestrator/services/broker_submission.py` | `DispatchDecision`, `attempt_broker_submission` |
| `src/knowledge_orchestrator/services/classification.py` | `TopicClassifier (classify)`, `calculate_obsolescence_date`, `is_obsolete` |
| `src/knowledge_orchestrator/services/domain_enrichment.py` | `DomainEnrichmentService (__init__, enrich_capture, enrich_unassigned_pending)` |
| `src/knowledge_orchestrator/services/file_stability.py` | `FileStabilityChecker (__init__, wait_until_stable)`, `read_bytes_with_lock_retries` |
| `src/knowledge_orchestrator/services/filesystem.py` | `write_synced`, `atomic_write_json`, `unique_destination` |
| `src/knowledge_orchestrator/services/ingestion.py` | `IngestionService (__init__, request_cancel, clear_cancel, ingest, _reject)` |
| `src/knowledge_orchestrator/services/model_discovery.py` | `ModelDiscoveryService (__init__, refresh)` |
| `src/knowledge_orchestrator/services/operations.py` | `JsonFormatter (format)`, `BackupResult`, `DiagnosticResult`, `configure_logging`, `shutdown_logging`, `backup_database`, `export_diagnostics`, `sanitize`, `_redact`, `_database_summary`, `_directory_summary`, `_read_log_tail` |
| `src/knowledge_orchestrator/services/profile_service.py` | `ProfileService (__init__, list_profiles, get_profile, save_profile, set_enabled)` |
| `src/knowledge_orchestrator/services/prompting.py` | `PromptRenderError`, `PromptRenderer (render)`, `estimate_tokens`, `TextChunker (split, _split_oversized)`, `prompt_context`, `build_chat_request` |
| `src/knowledge_orchestrator/services/publication.py` | `PublicationError`, `ResultMarkdownError`, `validate_result_markdown`, `_safe_filename`, `_safe_identifier`, `PublicationService (__init__, publish_ready, publish, recover, reject, _finish_rejection, reprocess, _resume_reprocess…)` |
| `src/knowledge_orchestrator/services/quarantine.py` | `QuarantineService (__init__, quarantine, recover_pending, _complete_intent, _validate_managed_paths)` |
| `src/knowledge_orchestrator/services/recovery.py` | `RecoveryReport`, `RecoveryService (__init__, recover, _fail_capture, _complete_staged, _repair_pending, _adopt_orphan, _find_inbox_by_hash, _verify…)` |
| `src/knowledge_orchestrator/services/semantic_broker.py` | `SemanticBrokerProcessor (__init__, dispatch_once, poll_once)` |
| `src/knowledge_orchestrator/services/semantic_maintenance.py` | `SemanticContractError`, `SemanticMaintenanceService (__init__, extraction_prompt, comparison_prompt, broker_json_request, embedding_request, ingest_embedding_result, schedule_extraction, schedule_comparison…)` |
| `src/knowledge_orchestrator/services/topic_service.py` | `TopicService (__init__, list_topics, save_topic, reorder_topics, ensure_folder, ensure_all_folders)` |
| `src/knowledge_orchestrator/services/workflow_planner.py` | `WorkflowPlanner (__init__, plan_unplanned, plan_capture, advance_workflow, _create_single_fallback_if_needed, _create_fallback_if_needed, _task, _assistant_content)` |
| `src/knowledge_orchestrator/ui/dashboard.py` | `OrchestratorDashboard (__init__, start, _configure_style, _build, _build_header, _build_action_bar, _new_page, _build_home…)`, `run_dashboard`, `data_root_label`, `available_profile_strategies` |
| `src/knowledge_orchestrator/ui/event_bridge.py` | `UiEventBridge (__init__, drain)` |
| `src/knowledge_orchestrator/ui/snapshots.py` | `DashboardSnapshot`, `QueueItem`, `WorkItem`, `WorkEvent`, `ReviewItem`, `TopicItem`, `ProfileItem`, `UiSnapshotService (__init__, dashboard, queue, work_items, work_events, reviews, topics, profiles…)`, `_safe_json`, `_progress_text`, `_elapsed_seconds`, `_work_category` |
| `src/knowledge_orchestrator/worker/broker_worker.py` | `BrokerWorker (__init__, start, stop, capabilities_snapshot, request_cancel, _run, _run_async, _refresh_capabilities…)` |
| `src/knowledge_orchestrator/worker/inbox_watcher.py` | `ObserverLike (schedule, start, stop, join)`, `_InboxEventHandler (__init__, on_created, on_modified, on_moved, _submit_file)`, `InboxWatcher (__init__, start, stop, scan_once, _scan_loop)` |
| `src/knowledge_orchestrator/worker/ingestion_worker.py` | `IngestionWorker (__init__, start, submit, retry, stop, _run, _fingerprint)` |

# Roadmap (fases claras)

## Fase 0
Reproducibilidad y characterization tests.

## Fase 1
Runtime/tooling moderno.

## Fase 2
Arquitectura y deuda.

## Fase 3
Hardening/operaciones.

# TAREAS_UPGRADE_MODERNIZACION

## UGM-001 — Migrar a Python 3.13
- **Archivos:** `pyproject.toml`, scripts, CI, docs.
- **Pasos:** matriz 3.11/3.13; arreglar incompatibilidades; retirar 3.11 tras release.
- **Aceptación:** gates verdes y build Windows en 3.13.
- **Prioridad:** P0.
- **Severidad/riesgo:** High, 20.
- **Esfuerzo:** M.

## UGM-002 — Toolchain majors
- **Archivos:** manifest/lock/config.
- **Pasos:** pytest 9, mypy 2, ruff actual; resolver warnings/errors.
- **Aceptación:** cero bypasses nuevos sin justificación.
- **Dependencias:** UGM-001.
- **Prioridad:** P0.
- **Severidad/riesgo:** Medium, 12.
- **Esfuerzo:** M.

## UGM-003 — Refactor Dashboard
- **Archivos:** `ui/dashboard.py` + módulos `ui/views/*`.
- **Pasos:** characterization snapshots; extraer una vista por PR; presenter tests.
- **Aceptación:** `dashboard.py` queda como shell/composition UI, comportamiento visual conservado.
- **Dependencias:** CI estable.
- **Prioridad:** P1.
- **Severidad/riesgo:** Medium, 16.
- **Esfuerzo:** L.

## UGM-004 — Extraer transición de workflow
- **Archivos:** `workflow_repository.py`, domain/services, tests.
- **Pasos:** modelar transición pura; persistencia en transacción; parametrizar estados.
- **Aceptación:** `apply_status()` deja de contener parseo+reglas+persistencia monolíticos.
- **Prioridad:** P1.
- **Severidad/riesgo:** Medium, 15.
- **Esfuerzo:** M.

## UGM-005 — Pipeline explícito de ingesta
- **Archivos:** `services/ingestion.py`, recovery/tests.
- **Pasos:** extraer validate/stage/persist/move/finalize; conservar checkpoints.
- **Aceptación:** cada paso es testeable e idempotente.
- **Prioridad:** P1.
- **Severidad/riesgo:** High, 16.
- **Esfuerzo:** M.

## UGM-006 — Observabilidad operacional
- **Archivos:** `operations.py`, worker/services.
- **Pasos:** definir campos, métricas, auth state, contract mismatch state.
- **Aceptación:** diagnóstico permite distinguir red/auth/contrato/retry sin leer secretos.
- **Prioridad:** P1.
- **Severidad/riesgo:** Medium, 12.
- **Esfuerzo:** M.

## UGM-007 — Perfil Broker hardened
- **Archivos:** `config.py`, `broker_client.py`, docs.
- **Pasos:** modo LAN explícito; modo hardened con HTTPS/token; validación fail-fast.
- **Aceptación:** no es posible desplegar accidentalmente un perfil hardened sobre HTTP.
- **Prioridad:** P1.
- **Severidad/riesgo:** High, 16.
- **Esfuerzo:** M.

## UGM-008 — Pipeline de supply-chain
- **Archivos:** CI.
- **Pasos:** SBOM, SCA, secret scan, artifact provenance básica.
- **Aceptación:** cada release conserva versiones exactas e informe.
- **Prioridad:** P1.
- **Severidad/riesgo:** High, 16.
- **Esfuerzo:** M.

## UGM-009 — E2E de release
- **Archivos:** scripts/tests/docs.
- **Pasos:** fixture real o entorno controlado; Plugin/import → Broker → Obsidian; archivar logs/resultados saneados.
- **Aceptación:** evidencia reproducible por release.
- **Prioridad:** P1.
- **Severidad/riesgo:** High, 16.
- **Esfuerzo:** L.

# Verificación y checklist post-modernización

- [ ] Build Windows Python 3.13.
- [ ] Unit/integration/contract tests.
- [ ] Ruff sin errores.
- [ ] Mypy 2 sin regresiones ocultadas.
- [ ] UI snapshot/interaction smoke.
- [ ] Crash recovery en checkpoints.
- [ ] Backup/restore drill.
- [ ] Broker 2.8/2.9 contract suite.
- [ ] Métricas y logs correlacionados.
- [ ] Redaction tests.
- [ ] SBOM/SCA/secret scan.
- [ ] E2E release archivado.
- [ ] Rollback documentado a versión anterior + copia DB.

# Supuestos y límites

- Modernización diseñada por lectura; no se ha validado contra ejecución real.
- No se propone cambiar SQLite/Tkinter por moda: el stack actual encaja con desktop local.
- No se propone httpx 1.0 mientras siga prerelease.
- Los refactors deben hacerse tras characterization tests para preservar recovery/idempotencia.
- **NEXT_PHASE_ASK:** para continuar con una auditoría de touchpoints 100% a nivel método/línea, elegir el siguiente lote por carpeta: `repositories`, `services`, `worker/integrations`, `domain` o `ui`.
