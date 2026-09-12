# Evidencia de aceptación del ciclo de conocimiento

Auditoría inicial, 7 de septiembre de 2026. Conserva los veinte escenarios obligatorios
de la especificación; **no declara completados los criterios globales ni los checkpoints
visuales**. Se inspeccionaron las aserciones de las pruebas citadas, no solo sus nombres.
Los casos usan bases y documentos temporales, Broker simulado y, donde se indica, HTTP local.
El resultado de la batería vigente se registra en `CURRENT_STATE.md`.

## Veinte escenarios obligatorios

Las referencias siguientes son archivos bajo `tests/`. “Local” acredita el escenario
controlado descrito; no demuestra comportamiento de un modelo real ni una sesión visual.

| # | Requisito | Evidencia inspeccionada | Estado |
|---|---|---|---|
| 1 | Nueva versión oficial sustituye CURRENT | `test_automation_execution.py::test_approved_policy_publishes_once_with_original_history_and_attribution`; fixture con documentos oficiales/versiones 1 y 2 y política autorizada | Local |
| 2 | Claim anterior conserva histórico | `test_phase_nine_knowledge_core.py::test_approved_successor_preserves_unaffected_claim_and_full_evidence`; estado, sucesor, fecha final, revisión y cita anteriores | Local |
| 3 | Otro claim de la nota sigue CURRENT | Mismo caso anterior; identificador del span no sustituido permanece en consulta current | Local |
| 4 | Fuente secundaria contradice oficial sin actualización silenciosa | `test_phase_twelve_knowledge_maintenance.py::test_secondary_conflicting_source_requires_explicit_human_resolution`; ambas DISPUTED y archivo intacto antes de decisión | Local |
| 5 | Dos fuentes fiables requieren revisión | `test_two_high_trust_sources_do_not_resolve_by_trust_or_model_confidence`, mismo archivo; PENDING_REVIEW y autoapproval no elegible | Local |
| 6 | manual_lock impide actualización | `test_phase_nine_knowledge_core.py::test_manual_lock_after_diff_prevents_note_and_claim_changes` y `test_automation_execution.py::test_manual_lock_added_after_simulation_is_absolute` | Local |
| 7 | Edición externa después del diff da CONFLICT | Ruta check/replace retirada. T12 conserva edición antes del callback; Node comprueba base dentro del callback; `test_obsidian_maintenance_integration.py` verifica runtime sin fallback, recibo ambiguo, respuesta perdida y recuperación | Integración local verificada con editor simulado; Obsidian real pendiente, ver `Note_Replacement_Coordination.md` |
| 8 | Aprobación individual | `test_phase_twelve_knowledge_maintenance.py::test_api_review_scopes_revision_conflict_and_repeated_approval` y prueba de sucesor de fase 9 | Local; widgets pendientes |
| 9 | Selección masiva y resultados parciales por tarea | `test_review_batches.py::test_confirmed_selection_reports_partial_results_and_preserves_late_edit`; una APPLIED, otra CONFLICT, repetición sin trabajo adicional | Local; widgets pendientes |
| 10 | Autoaprobación solo de elegibles | `test_automation_execution.py`: política desactivada/pausa, fuente revocada, edición y manual_lock revalidados antes de reserva | Local |
| 11 | Política editada conserva versiones | `test_automation_governance.py::test_edit_revokes_activation_and_preserves_immutable_versions_and_decisions`; umbrales anteriores, decisiones 0/1/0 y triggers inmutables | Local |
| 12 | Recuperación tras caída al publicar | `test_phase_nine_knowledge_core.py::test_recovery_registers_exactly_one_temporal_transition`; recuperar dos veces produce una sola transición | Local |
| 13 | Caída en vigilancia no duplica ingestión | `test_phase_eleven_source_monitoring.py::test_delivery_recovers_crash_between_receipt_and_link_with_provenance`; runtime nuevo, una ingesta/un archivo y procedencia original | Local |
| 14 | API current excluye histórico | `test_phase_ten_knowledge_api.py::test_current_and_history_are_distinct_in_claims_search_and_entity_history`; IDs vigentes, 404 individual por defecto e histórico explícito | Local |
| 15 | API history reconstruye sucesión | Mismo caso anterior; CURRENT/SUPERSEDED y dos transiciones del claim anterior | Local |
| 16 | Query aporta evidencias | `test_query_returns_grounded_quotes_with_durable_broker_task_and_owner_isolation`, mismo archivo; cita, claim, tarea durable y consumidor | Local; inferencia real pendiente |
| 17 | Query reconoce insuficiencia | `test_empty_retrieval_reports_insufficient_without_broker`, mismo archivo; respuesta explícita y evidencia vacía | Local |
| 18 | Instrucciones maliciosas dentro de una fuente no alteran reglas | `test_untrusted_source_boundaries.py`: fuente vigilada con etiquetas/órdenes adversarias; delimitadores protegidos, respuestas fuera de contrato rechazadas sin claims parciales, propuesta sin publicación, manual_lock y confianza configurada conservados | Barreras locales verificadas; modelo real pendiente |
| 19 | Backoff de fuente caída sin bloquear otra | `test_phase_eleven_source_monitoring.py::test_backoff_one_error_does_not_block_other_source`; HTTP_503 simulado, segunda CHANGED y espera creciente | Local; red real pendiente |
| 20 | Cambios triviales sin ruido | `test_html_trivial_markup_ignored_but_code_indent_preserved` y `test_rss_dates_and_order_do_not_change_item_hashes`, mismo archivo; hashes estables salvo contenido relevante | Local |

## Evidencia que aún no permite cerrar el proyecto

- Fase 13 exige checkpoint **visual y funcional**. En el incremento 23 las cinco
  pruebas nativas antes omitidas se ejecutan al inicializar Tcl antes del escritorio;
  los 70 casos de sus módulos pasan. Esto añade comportamiento real de widgets,
  pero no reemplaza la inspección visual de ventanas, foco, contraste y navegación
  integral por el usuario. La batería vigente consta en `CURRENT_STATE.md`.
  Tras corregir el cierre de ventanas, la batería completa con inicialización de
  escritorio pasa: **454 pruebas en 325,693 s, sin omisiones**.
- La revisión independiente de reversión y del puente propuesta/política terminó sin
  correcciones pendientes. La revisión integral anterior de Servicios/políticas quedó
  sin completar por cuota; la revisión acotada del décimo incremento no reemplaza el
  checkpoint visual ni acredita todos los flujos anteriores.
- Broker/red: el último diagnóstico disponible fue WinError 10013/NETWORK_DENIED
  antes de HTTP. El token nuevo no acredita conectividad. HTTP loopback sí tiene
  evidencia separada, sin inferencia externa.
- Debe demostrarse el flujo real Plugin → Orchestrator → Broker → Obsidian. No se
  sustituye por fixtures, mocks ni publicaciones manuales de resultados simulados.
- El caso 18 ya tiene pruebas adversarias de documento fuente en las fronteras de
  extracción/comparación/publicación. Acreditan delimitación reversible y rechazo
  estructural de autoridad no admitida; no prueban obediencia de un LLM real. Una
  cita literal de una fuente no equivale a un hecho verificado. La inferencia real
  conserva su requisito de ensayo externo.
- Los campos/eventos están en `Proposal_Audit_Evidence.md`; las entregas de fase,
  contratos, guardas y criterios globales se detallan en `Delivery_Acceptance_Audit.md`.
  Los requisitos parciales o sin prueba real siguen abiertos. Esta tabla de veinte
  escenarios no redefine el alcance ni sustituye los checkpoints pendientes.

La matriz [Proposal_Audit_Evidence.md](Proposal_Audit_Evidence.md) añade los diecinueve
campos de propuesta, doce categorías de observabilidad y diez preguntas de reconstrucción.
El undécimo incremento corrige los eventos ausentes de análisis/conflictos e incorpora
pruebas transaccionales. El duodécimo añade consulta de trazabilidad desde Revisión e
Histórico con versiones, tareas/modelos y decisión original; el render y recorrido
visual integral sigue pendiente. El inventario global está disponible en
[Delivery_Acceptance_Audit.md](Delivery_Acceptance_Audit.md), con evidencia y pendientes explícitos.
El decimotercer incremento protege logs/diagnóstico y evita duplicar snippets de YAML
rechazado en eventos/sidecars. Nueve pruebas nuevas y batería de 408 pruebas (403 pasan,
cinco omisiones Tcl/Tk); no acredita anonimización de todos los textos libres históricos.
El decimocuarto incorpora ese inventario y minimiza eventos de avisos/citas/fallback
de workflows; tres pruebas nuevas y batería de 411 pruebas (406 pasan, cinco omisiones).
El decimoquinto verifica la guarda de fecha sola: tres pruebas con evidencia antigua,
observación posterior sin cambio y reemplazo inferido sin cita; avance de reloj y
reinicio no cambian notas/claims/historial ni crean publicaciones o reservas automáticas.
Batería completa final: 414 pruebas en 220,593 s; 409 pasan y cinco omisiones Tcl/Tk.
No se han activado políticas ni
modificado documentos del usuario para obtener esta evidencia.

## Hallazgo al revisar los campos de propuesta

Incremento 22: `test_maintenance_windows_newlines.py` añade cuatro casos que verifican
conflictos por cambios LF/CRLF en base, resultado y evidencia, además de aprobación y
reversión de una nota CRLF conservando exactamente sus bytes originales. Fallaban antes
de corregir la normalización implícita de lectura. Refuerzan los escenarios 7 y 12 con
editor simulado; el resultado general vigente figura en `CURRENT_STATE.md`.

Incremento 20: cuatro regresiones adicionales de mantenimiento reproducen cambios de
codificación antes/después de la intención, evidencia ilegible y recuperación con otra
nota independiente. Tras corregir el manejo de lectura, se conserva el archivo humano,
el snapshot previo y el conflicto durable; otra aplicación recupera sin duplicarse.
No se convierten documentos del usuario ni se acredita una sesión real de Obsidian.
Regresión completa: 445 casos, 440 pasan y cinco omisiones Tcl/Tk; Ruff/mypy correctos.
Alcance en `Phase_14_Automation_Governance.md`.

Incremento 18: entorno Obsidian/Windows/local confirmado. Puente integrado con runtime,
aprobación, recuperación y reversión; conexión DPAPI propia y panel de Ajustes. Se retiró
la sustitución directa de notas existentes. Batería general: 440 casos en 293,853 s,
435 pasan y cinco omisiones Tk. Diez pruebas de conexión/integración pasan, incluyendo
un caso API 503 añadido después de esa batería. Diez Node adicionales pasan;
Ruff/mypy (149 archivos) y diff pasan. El caso 7 ahora tiene integración verificada con
editor simulado, sin acreditar todavía una sesión real de Obsidian ni render de Ajustes.

Incremento 17: `test_publication_conflicts.py` añade seis casos de creación de nota sin
sustituir un destino ocupado, con fuente/edición conservadas, conflicto durable,
recuperación y continuidad de otras notas. Incluye escritura desde otro proceso justo
antes de instalar y caída tras enlace antes de limpiar el temporal. Batería vigente:
425 pruebas en 255,751 s; 420 pasan y cinco omisiones Tcl/Tk; Ruff/mypy (146 archivos)
y diff pasan. Esto no certifica reemplazo condicional de notas existentes ni Obsidian real.

Actualización de observabilidad, incremento 16: el cliente Broker oculta credenciales
en errores HTTP/de conexión y objetos de error antes de guardarlos. Cinco pruebas
adicionales cubren rotación con respuesta tardía, almacenamiento semántico/workflow,
traceback y reintento durable. Batería vigente: 419 pruebas en 187,072 s; 414 pasan,
cinco omisiones Tcl/Tk; Ruff/mypy (146 archivos) y diff pasan. Todo con credenciales
ficticias y datos temporales; integración externa y render siguen sin acreditarse.

`services/maintenance_assessment.py` construye descripción, claims, entidades,
evidencia anterior/nueva, confianza configurada, relación, justificación, impacto,
notas/claims afectados, patch, riesgos y trabajos de análisis. `proposal_detail`
incluye revisión, versiones, actor y sucesor; las versiones conservan fechas.

**Resuelto en el décimo incremento de fase 14:** los assessments nuevos declaran
`policy_evaluated=false` y `POLICY_EVALUATION_REQUIRED`. El detalle añade
`automation_review` separado del snapshot; el puente Revisión → Evaluar con política
transfiere exactamente propuesta/revisión a la simulación de una política explícita.
`test_proposal_policy_review.py` verifica siete casos: política existente, snapshot
legacy byte a byte mediante API, selección única/borrador, revisión obsoleta, respuesta
perdida, historial de otra propuesta/revisión y navegación. Las pruebas preservan
pausa, políticas desactivadas y notas temporales. La revisión independiente de este
incremento no deja hallazgos materiales; render y prueba con modelo real siguen pendientes.
