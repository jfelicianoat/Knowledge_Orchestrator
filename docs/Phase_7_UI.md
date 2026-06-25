# Fase 7 — Cola visual y UX de espera

## Estado

Primera entrega implementada y verificada. La UI Tk arranca con `--ui`, consume eventos solo desde el hilo principal, refresca snapshots cada 2 segundos y permite revisar candidatos semánticos pendientes.

## Alcance implementado

- Ventana Tk con pestañas Dashboard, Cola, Revisión, Temas y Configuración.
- Servicio `UiSnapshotService` de solo lectura para desacoplar widgets de repositorios de escritura.
- Dashboard con capturas activas, candidatos pendientes, fallos, notas publicadas y último estado conocido del Broker.
- Cola visual con posición, estado, fase, modelo, paso, tiempo transcurrido e intentos.
- Spinner únicamente sobre la primera tarea `PROCESSING`; las tareas en espera muestran posición y estado.
- Revisión semántica con diff, rationale, bloqueo y acciones explícitas de aprobar o rechazar.
- Pestañas de Temas y Configuración en modo lectura para validar asignaciones y perfiles activos.
- Entrada CLI `python -m knowledge_orchestrator.app --ui`.

## Restricciones mantenidas

- La UI no inventa porcentajes. Si el Broker no entrega progreso medible, se muestran fase, texto de progreso y tiempo transcurrido.
- Los workers no modifican widgets. Publican `ApplicationEvent` en la cola thread-safe y Tk la drena en el hilo principal.
- Las acciones de revisión llaman a servicios de dominio existentes: aprobación atómica mediante `SemanticMaintenanceService.approve` y rechazo mediante `SemanticRepository.mark_candidate`.
- La UI no accede a HTTP del Broker ni coordina LLMs; solo presenta estado persistido por el Orchestrator.

## Verificación

- `tests/test_phase_seven_ui_snapshots.py` cubre snapshots de cola, dashboard, revisión, temas y perfiles.
- La suite completa alcanza 82 pruebas con `python -m unittest discover -s tests -v`.

## Pendiente para iteraciones posteriores

- Edición visual completa de temas y perfiles con validación optimista.
- Vista comparativa más rica para revisión de notas completas y reprocesado manual.
- Tests visuales/manuales en Windows con una sesión larga real contra AI Broker.
