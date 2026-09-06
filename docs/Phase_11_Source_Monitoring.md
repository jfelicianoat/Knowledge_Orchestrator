# Fase 11 — Source monitoring

1. **Estado encontrado.** No había productores autónomos. Se reutilizan la ingesta API
   idempotente, SQLite, auditoría y publicación/revisión existentes, manteniendo Tkinter.
2. **Diseño.** Connector con Web y RSS/Atom, configuración versionada, reservas durables,
   hashes por ítem, procedencia original y revisión inicial por defecto. Scheduler
   independiente del Broker y de la UI.
3. **Cambios.** ETag/Last-Modified, normalización acotada, descargas protegidas, estados,
   backoff, comprobaciones manuales, scope API sources y pestaña Fuentes. No se registran
   fuentes automáticamente ni se aprueban cambios de conocimiento al incorporar novedades.
4. **Archivos.** domain/monitoring.py, repositories/source_repository.py,
   integrations/source_http.py y source_connectors.py, services/source_monitoring.py,
   worker/source_worker.py, ui/dashboard/fuentes.py, runtime/UI, contratos API,
   procedencia en knowledge_access.py y tests/test_phase_eleven_source_monitoring.py.
5. **Migraciones.** 014 aditiva: fuentes, revisiones inmutables, comprobaciones,
   observaciones, hashes por ítem y comandos idempotentes. Sin recrear datos previos.
6. **Tests.** 21 casos nuevos: A→B→A, 304, versiones y resultados caducados, reservas,
   errores aislados, entrega interrumpida, procedencia, backoff, atomicidad de lote,
   concurrencia sin Broker, permisos, HTML/código, RSS/Atom, XML malicioso, redirecciones,
   credenciales, IP pública, tamaño/truncamiento y UI cuando Tcl/Tk está disponible.
7. **Verificación (2026-09-05).** Unittest: **210 tests, 209 pasan, 1 omitido**, 33,415 s.
   Ruff pasa. Mypy pasa (103 archivos). Descarga pública con conector real:
   **NO VERIFICADO**, NETWORK_DENIED. Tk: **NO VERIFICADO**, no carga init.tcl;
   tampoco usando una copia temporal de la biblioteca instalada. La omisión solo cubre
   ausencia explícita de runtime Tcl/display, no errores de widgets.
8. **Riesgos.** Descargas y pantalla requieren prueba real; DNS conserva timeout del SO.
   El cierre puede dejar una comprobación recuperable. DELIVERED no significa publicado.
   Sin identidad RSS estable se usa hash; contenido dependiente de JS no se observa.
9. **Checkpoint.** Núcleo, recuperación, API y calidad verificados localmente. Red y
   pantalla pendientes por condiciones externas documentadas; sin tests conocidos de
   lógica fallando. Este checkpoint no acredita la cadena externa.
10. **Siguiente.** Fase 12: impacto/procedencia/riesgos de propuestas, revisión,
    transformación segura de notas y reindexado. Mantener visibles las verificaciones
    externas pendientes y el objetivo completo de fases 9–14.

Operación y contratos: [Source_Monitoring.md](Source_Monitoring.md).
