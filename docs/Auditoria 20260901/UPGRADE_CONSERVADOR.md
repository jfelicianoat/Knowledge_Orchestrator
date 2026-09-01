# Resumen ejecutivo de actualización (conservador)

Objetivo: recuperar margen de soporte y reproducibilidad con el menor cambio posible.

1. Elevar baseline de Python de `>=3.10` a **`>=3.11`**.
2. Mantener las familias productivas actuales: PyYAML 6, watchdog 6, httpx 0.28.x.
3. Introducir lockfile/constraints reproducibles sin re-arquitecturar.
4. Mantener pytest 8 y mypy 1.x inicialmente para minimizar breaking changes.
5. Corregir la incompatibilidad diagnóstica Broker 2.8/2.9.
6. Añadir CI con build/lint/typecheck/tests, sin cambiar comportamiento funcional.
7. No introducir TLS obligatorio en el perfil LAN; sí documentar y validar explícitamente el modo de confianza.

# Fuentes de versiones (FUENTES_DE_VERSION)

| Componente | Versión detectada | Fuente | Confianza | Comentario |
|---|---|---|---|---|
| Python | `>=3.10` | `pyproject.toml` | Alta | mínimo, no versión exacta |
| setuptools | `>=68` | `pyproject.toml` build-system | Alta | sin lock/tope |
| PyYAML | `>=6.0,<7` | `pyproject.toml` | Alta | puede resolver 6.0.3 actualmente |
| watchdog | `>=4.0,<7` | `pyproject.toml` | Alta | puede resolver 6.0.0 actualmente |
| httpx | `>=0.27,<1` | `pyproject.toml` | Alta | estable actual 0.28.1; 1.0 sigue prerelease |
| pytest | `>=8.0,<9` | `pyproject.toml` dev | Alta | bloquea pytest 9 |
| ruff | `>=0.6,<1` | `pyproject.toml` dev | Alta | admite releases 0.x actuales |
| mypy | `>=1.10,<2` | `pyproject.toml` dev | Alta | bloquea mypy 2 |
| SQLite | stdlib Python | `database.py` | Media | versión depende del runtime Python |
| AI Broker contract | acepta 2.8/2.9 según docs; warning espera 2.8 | `docs/CURRENT_STATE.md`, `broker_worker.py` | Alta | deuda conocida |

# Referencias (EOL/soporte/CVEs/breaking changes) con fecha consultada

Fecha consultada: **2026-09-01**.

| Afirmación | Fuente |
|---|---|
| Python 3.10 está en security y EOL 2026-10; 3.11 EOL 2027-10; 3.13 bugfix y EOL 2029-10 | Python Developer Guide — https://devguide.python.org/versions/ |
| PyYAML estable más reciente observada: 6.0.3 (2025-09-25) | PyPI — https://pypi.org/project/PyYAML/ |
| watchdog estable más reciente observada: 6.0.0 | PyPI — https://pypi.org/project/watchdog/ |
| httpx estable más reciente observada: 0.28.1; 1.0.dev* es prerelease | PyPI — https://pypi.org/project/httpx/ |
| pytest 9.1.1 existe y requiere Python >=3.10 | PyPI — https://pypi.org/project/pytest/ |
| ruff 0.16.x existe en agosto de 2026 | PyPI — https://pypi.org/project/ruff/ |
| mypy 2.3.1 existe en agosto de 2026 | PyPI — https://pypi.org/project/mypy/ |
| setuptools 84.0.0 existe en agosto de 2026 | PyPI — https://pypi.org/project/setuptools/ |

**CVE:** no se asigna CVE a una dependencia concreta porque el proyecto no fija la versión instalada. La acción conservadora es crear lock/SBOM y ejecutar SCA sobre versiones exactas.

# Matriz de obsolescencia (MATRIZ_DE_OBSOLESCENCIA)

| Área | Estado | Evidencia | Consecuencia | Acción |
|---|---|---|---|---|
| Runtime Python | Riesgo alto | mínimo 3.10; EOL 2026-10 | soporte/security | subir a 3.11 |
| PyYAML | OK/riesgo de reproducibilidad | rango 6.x | instalaciones variables | lock 6.0.3 validado |
| watchdog | OK/riesgo de reproducibilidad | rango 4..<7 | instalaciones variables | lock 6.0.0 tras tests |
| httpx | OK | rango 0.27..<1; estable 0.28.1 | bajo | lock 0.28.1 |
| pytest | Riesgo bajo | <9 | tooling atrasado 1 major | mantener 8.x conservador |
| mypy | Riesgo medio | <2 | tooling atrasado 1 major | mantener 1.x conservador |
| ruff | OK | <1 | compatible con 0.x | fijar versión concreta |
| Build backend | Riesgo | setuptools >=68 | build variable | fijar/lock |
| CI | Obsoleto/ausente | no hay workflow visible | sin gate reproducible | añadir CI |
| Broker contract diag | Riesgo | hardcode 2.8 | warning falso con 2.9 | corregir |

# Targets recomendados (mínimo viable) y justificación

| Componente | Target conservador | Justificación |
|---|---|---|
| Python | 3.11.x mínimo | evita EOL inmediato con cambio de lenguaje pequeño |
| PyYAML | 6.0.3 | dentro del rango existente |
| watchdog | 6.0.0 | dentro del rango existente |
| httpx | 0.28.1 | estable, dentro del rango |
| pytest | último 8.x validado | evita major 9 en la primera ola |
| ruff | 0.16.x validado | dentro de `<1` |
| mypy | último 1.x validado | evita major 2 en la primera ola |
| setuptools | versión concreta validada | reproducibilidad del build |
| Broker contract | 2.8 y 2.9 compatibles | alinear warning con validador/documentación |

# Plan de cambios por área

## Runtime
- Cambiar `requires-python` a `>=3.11`.
- Actualizar `ruff.target-version` a `py311`.
- Actualizar `mypy.python_version` a `3.11`.
- Verificar scripts/installer con Python 3.11.

## Dependencias
- Resolver una vez en entorno limpio.
- Versionar lockfile.
- Mantener majors productivas actuales.
- Generar SBOM o al menos `pip freeze` firmado/archivado por release.

## Toolchain/build
- Fijar setuptools en lock/constraints.
- Añadir `python -m build` al CI si el proyecto distribuye wheel/sdist.

## Config
- Mantener defaults actuales.
- Añadir validación de URL Broker y warning claro si `http://` se usa fuera del perfil LAN.

## CI/CD
- Workflow Windows (principal) + opcional Linux para lógica no-Tk.
- Checks: tests, ruff, mypy.
- Cache dependencias por lock hash.

## Infra
No se detectaron Docker/Kubernetes/Terraform en el snapshot.

# Touchpoints de cambio (TOUCHPOINTS_DE_CAMBIO)

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

### Touchpoints directos del upgrade conservador

| Ruta | Cambio | Riesgo | Test |
|---|---|---|---|
| `pyproject.toml` | Python 3.11 + tooling versions | High | install + unit suite |
| `worker/broker_worker.py` | aceptar contract 2.9 | Medium | contract test capabilities |
| `tests/test_broker_worker.py` | caso 2.9 sin warning | Medium | pytest/unittest |
| `scripts/build_windows.ps1` | runtime/build pin | Medium | build smoke |
| `start_orchestrator.bat` | verificar launcher Python | Low | launch smoke |
| `.github/workflows/*` (nuevo) | quality gates | Low | CI green |
| lockfile (nuevo) | pins exactos | High | clean install |
| `README.md`, `docs/CURRENT_STATE.md` | baseline y comandos | Low | doc review |

# Roadmap (Quick wins / Medio / Largo)

## Quick wins
- Broker 2.9 warning.
- Python 3.11.
- Lockfile.
- CI.
- Docs.

## Medio
- SCA/SBOM.
- Hardening de config Broker.
- Restore test de backups.

## Largo
- E2E real archivado por release.
- Preparar salto Python 3.13.

# TAREAS_UPGRADE_CONSERVADOR

## UGC-001 — Baseline Python 3.11
- **Descripción:** eliminar dependencia operativa de 3.10 antes de EOL.
- **Archivos:** `pyproject.toml`, scripts/docs.
- **Pasos:** cambiar metadatos; instalar limpio; ejecutar gates.
- **Aceptación:** package instala y checks pasan en 3.11.
- **Dependencias:** ninguna.
- **Prioridad:** P0.
- **Severidad/riesgo:** High, 20.
- **Esfuerzo:** S.

## UGC-002 — Lock reproducible
- **Descripción:** fijar todas las dependencias directas/transitivas.
- **Archivos:** `pyproject.toml` + lock nuevo.
- **Pasos:** escoger herramienta; resolver; versionar; CI desde lock.
- **Aceptación:** dos instalaciones limpias resuelven los mismos artefactos.
- **Dependencias:** UGC-001.
- **Prioridad:** P0.
- **Severidad/riesgo:** High, 16.
- **Esfuerzo:** S.

## UGC-003 — Corregir diagnóstico Broker 2.9
- **Archivos:** `worker/broker_worker.py`, test.
- **Pasos:** definir versiones compatibles; sustituir literal; probar 2.8/2.9/desconocida.
- **Aceptación:** 2.9 no genera warning falso.
- **Prioridad:** P0.
- **Severidad/riesgo:** Medium, 15.
- **Esfuerzo:** S.

## UGC-004 — CI mínimo
- **Archivos:** workflow nuevo.
- **Pasos:** checkout, Python 3.11, install lock, tests, ruff, mypy.
- **Aceptación:** PR no mergeable con gate rojo.
- **Dependencias:** UGC-002.
- **Prioridad:** P0.
- **Severidad/riesgo:** Medium, 12.
- **Esfuerzo:** S.

## UGC-005 — SCA sobre versiones exactas
- **Archivos:** CI + SBOM/report.
- **Pasos:** generar SBOM; escanear; política de severidad.
- **Aceptación:** release conserva informe.
- **Dependencias:** UGC-002.
- **Prioridad:** P1.
- **Severidad/riesgo:** Medium, 12.
- **Esfuerzo:** M.

# Verificación y checklist post-upgrade

- [ ] Instalación limpia desde lock.
- [ ] `python -B -m unittest discover -s tests -v`.
- [ ] `python -m ruff check src tests`.
- [ ] `python -m mypy src`.
- [ ] Smoke de arranque UI.
- [ ] Smoke SQLite initialize/recover.
- [ ] Contract tests Broker 2.8 y 2.9.
- [ ] Backup + restore.
- [ ] Secret scan.
- [ ] Dependency/SBOM scan.
- [ ] E2E Plugin → Orchestrator → Broker → Obsidian cuando el entorno esté disponible.

# Supuestos y límites

- No se ejecutó la suite.
- No se conoce el entorno Python instalado por el usuario.
- Targets de paquetes deben quedar fijados solo después de ejecutar tests en el entorno real.
- El plan evita refactors estructurales.
