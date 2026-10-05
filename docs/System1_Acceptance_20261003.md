# Verificación de System 1 — 3 de octubre de 2026

El contrato actualizado afecta a los casos propios: omitir `threshold_profile` causaría `UNKNOWN_USE_CASE`. KO envía ahora `default` por defecto y permite perfiles distintos por uso. `target` se admite para llamadas explícitas de evaluación; los flujos de negocio siguen usando la política del Broker. Las notas de `attempts` quedan como diagnóstico y nunca sustituyen un rechazo de primer nivel. Una nota autodeclarada no habilita descartes.

Documento contrastado: `../../docs/Client_API.md`, contrato 2.11, SHA-256 `f773efab2a7862c5241819b2c17257a842c08d058838e19eff28e3dcdfe731d0`. Guía de arquitectura, configuración y límites: [System1_Integration.md](System1_Integration.md).

## Evidencia por requisito

| Requisito | Prueba / artefacto autoritativo |
|---|---|
| Reranking posterior a retrieval y reglas deterministas | `test_vector_retrieval_precedes_judgments_and_generator_sees_only_final_candidates`, `test_real_embeddings_rerank_and_return_exact_evidence`; se reutilizan `KnowledgeAccess.search` / `semantic_search`. |
| Evidencia exacta pese a menor similitud | Prueba con embeddings almacenados y respuesta final basada en la cita exacta. |
| Conservación mínima con todos los scores bajos | `test_all_low_scores_keep_original_minimum_and_confidence_is_not_relevance`. |
| Presupuesto del contexto seleccionado | `test_uncertain_band_and_budget`; presupuesto imposible restaura retrieval, `MIN_CHUNKS_BUDGET`. |
| Fallback con caída, rechazo, baja confianza y score sin calibrar | `test_failures_low_confidence_and_calibration_restore_original`, `test_broker_failure_during_rerank_preserves_original_request`. |
| Clasificación sustantivo/claim/relleno/promoción y ambigüedad | `test_technical_claim_and_ambiguous_retained_promotion_and_subscription_removed`. |
| Contexto adyacente a claims en investigación | `test_research_retains_adjacent_claim_context`. |
| Fuente, timestamps y trazabilidad de segmentos intactos | `test_youtube_worker_preparation_preserves_source_and_persists_segment_trace`; offsets verificados contra la transcripción. |
| Broker caído o rechazo parcial restaura transcripción completa | `test_rejected_halfway_or_offline_restores_full_original`; también límite de segmentos y contexto vacío. |
| Sin IA en YT_Capture_Plugin ni llamada directa a Laya/Ollama | Integración exclusiva mediante `BrokerClient.judge`, con `cloud_allowed: false`; cambios limitados a KO y artefactos de pruebas. |
| Umbrales/flags/sombra/perfiles configurables | `test_json_and_environment_overrides_and_validation`, `test_named_profiles_can_be_configured_separately`, pruebas de feature off y modo sombra. |
| Casos propios compatibles con contrato actualizado | `test_custom_use_cases_explicitly_request_default_thresholds`, con transporte HTTP controlado. |
| `target` de evaluación, nombre real de modelo y notas brutas | `test_target_is_evaluation_only_and_preserves_actual_model_name`, `test_rejected_raw_attempt_never_changes_business_context`. |
| `SELF_REPORTED_SCORE` nunca aplica lógica de negocio | Pruebas del rechazo y de una respuesta incoherente con `accepted: true` / `self_reported`. |
| No cambiar el cuerpo en reintentos; no enviar evidencia obsoleta | `test_prepared_request_survives_restart_and_retry_without_new_judgments`, `test_knowledge_changes_during_judge_block_stale_evidence`. |
| No bloquear cierre por juicios lentos | `test_stage_timeout_preserves_original_and_cancels_call`, `test_stop_interrupts_slow_judgment_without_submission`. |
| Métricas y las dos demostraciones reproducibles | `scripts/demo_system1.py` y `../../output/System1_Demo_20261003.json`. |

## Resultados medidos

| Escenario controlado | Antes | Después | Tokens estimados antes → después |
|---|---:|---:|---:|
| RAG | 12 candidatos | 2 candidatos | 730 → 117 |
| Transcripción para resumen | 5 segmentos | 3 segmentos | 138 → 85 |
| Transcripción para investigación | 5 segmentos | 4 segmentos | 138 → 112 |

Conservados en RAG: claims 10 y 11 (niveles de utilidad 1.0 y 0.8). El fixture etiquetado de esta demo tiene recall/precision 1.0/1.0 para la política con juicios suministrados. El escenario de resumen conserva S1/S4/S5; investigación añade S3 como contexto del claim. Los dos escenarios de Broker caído restauran sus originales. Ratios de fallback de esta demo: 1/2 escenarios RAG y 1/3 escenarios de transcripción.

Estos resultados son **de política con juicios simulados**, no rendimiento de un clasificador real. Los tokens se estiman con la función existente `ceil(caracteres/4)`, no con el tokenizador de un modelo. No se ha medido ahorro neto de inferencia, precisión de Nimble/Laya, latencia de proveedor ni calibración en contenido real. El modo sombra y `require_calibrated` permiten comprobar esa etapa antes de aplicar descartes.

## Comprobaciones ejecutadas

- Batería completa: **555 passed, 16 skipped, 188 subtests passed**, 379.61 segundos. Las pruebas de UI condicionadas por Tcl/Tk/entorno quedan fuera de la validación visual de esta ejecución.
- Comprobación final del contrato y la integración tras el último ajuste de validación: **69 passed, 23 subtests passed**, 8.88 segundos.
- Ruff: **All checks passed** en código, pruebas nuevas y demo.
- mypy: **Success: no issues found in 161 source files**.
- `git diff --check`: sin errores.
- Demo: ejecutada y salida inspeccionada; ambos fallbacks restauran los originales.

Comandos desde la carpeta del proyecto (los directorios temporales están fuera de los datos del usuario):

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests -p no:cacheprovider --basetemp ../output/test-runs/ko-system1-full-20261003
.\.venv\Scripts\python.exe -m pytest -q tests/test_system1.py tests/test_system1_integration.py tests/test_broker_client.py tests/test_broker_contracts.py -p no:cacheprovider --basetemp ../output/test-runs/ko-system1-final-validation
.\.venv\Scripts\python.exe -m ruff check src tests/test_system1.py tests/test_system1_integration.py scripts/demo_system1.py --no-cache
.\.venv\Scripts\python.exe -m mypy src --cache-dir ../output/mypy-ko-system1
.\.venv\Scripts\python.exe scripts/demo_system1.py --output ../output/System1_Demo_20261003.json
```

## Archivos de la integración

- Contrato y transporte: `domain/system1.py`, `domain/broker_contracts.py`, `integrations/broker_client.py`.
- Política/configuración: `services/system1.py`, `services/system1_settings.py`, `docs/system1.example.json`.
- RAG y persistencia: `services/knowledge_query.py`, `repositories/query_repository.py`, `api/contracts.py`, `api/application.py`.
- Preparación asíncrona: `runtime.py`, `services/workflow_planner.py`, `worker/broker_worker.py`.
- Verificación: `tests/test_system1.py`, `tests/test_system1_integration.py`, `scripts/demo_system1.py`.
- Documentación: este informe, `docs/System1_Integration.md`, `docs/CURRENT_STATE.md` y `README.md`.

Los paths de código del listado son relativos a `src/knowledge_orchestrator`. No se añade base de datos ni dependencia. `start_orchestrator.bat` ejecuta las fuentes actuales; activar los flags y reiniciar permite usar la integración. La selección está apagada por defecto. Los workflows ya planificados conservan su cuerpo y las planificaciones explícitas por la API síncrona mantienen su vía previa; el prefiltrado se aplica a las capturas nuevas que prepara el worker.
