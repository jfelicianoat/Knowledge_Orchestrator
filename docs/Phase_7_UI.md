# Fase 7 — Cola visual y UX de espera

> **Registro histórico de entrega.** La UI implementada usa Tkinter/ttk; estado vigente:
> [CURRENT_STATE.md](CURRENT_STATE.md).

## Estado

Primera entrega implementada y verificada. La UI Tk arranca con `--ui`, consume eventos solo desde el hilo principal, refresca snapshots cada 2 segundos y permite revisar candidatos semánticos pendientes.

## Alcance implementado

- Ventana Tk con vistas Resumen, Documentos, Biblioteca, Revisión, Organización y Ajustes.
- Servicio `UiSnapshotService` de solo lectura para desacoplar widgets de repositorios de escritura.
- Dashboard con capturas activas, candidatos pendientes, fallos, notas publicadas y último estado conocido del Broker.
- Cola visual con posición, estado, fase, modelo, paso, tiempo transcurrido e intentos.
- Spinner únicamente sobre la primera tarea `PROCESSING`; las tareas en espera muestran posición y estado.
- Revisión semántica con diff, rationale, bloqueo y acciones explícitas de aprobar o rechazar.
- Biblioteca consultable de notas publicadas, con tema, revisión y ubicación en Obsidian.
- Organización y Ajustes para validar asignaciones y editar políticas mediante términos comprensibles.
- Selección múltiple estable durante el refresco y envío inmediato por lote de los documentos marcados.
- La dirección y el token del Broker se recargan en caliente al guardarlos; no requieren reiniciar la aplicación.
- La ventana aparece antes de la recuperación e ingesta inicial; ese trabajo continúa en segundo plano sin bloquear Tk.
- Entrada CLI `python -m knowledge_orchestrator.app --ui`.

## Restricciones mantenidas

- La UI no inventa porcentajes. Si el Broker no entrega progreso medible, se muestran fase, texto de progreso y tiempo transcurrido.
- Los workers no modifican widgets. Publican `ApplicationEvent` en la cola thread-safe y Tk la drena en el hilo principal.
- Las acciones de revisión llaman a servicios de dominio existentes: aprobación atómica mediante `SemanticMaintenanceService.approve` y rechazo mediante `SemanticRepository.mark_candidate`.
- La UI no accede a HTTP del Broker ni coordina LLMs; solo presenta estado persistido por el Orchestrator.

## Verificación

- `tests/test_phase_seven_ui_snapshots.py` cubre snapshots de documentos, resumen, biblioteca, revisión, organización y perfiles, además de la estabilidad de selección.
- La suite completa se ejecuta con `python -m unittest discover -s tests -v`.

## Pendiente para iteraciones posteriores

- Edición visual completa de temas con validación optimista.
- API de consulta documental para consumidores externos, apoyada en una capa de servicio y no en el esquema SQLite ni en la interfaz Tk.
- Vista comparativa más rica para revisión de notas completas y reprocesado manual.
- Tests visuales/manuales en Windows con una sesión larga real contra AI Broker.
