# Evolución del ciclo de vida del conocimiento

Especificación de trabajo: petición del usuario del 5 de septiembre de 2026, fases 9–14.
El alcance completo permanece pendiente hasta superar todos los checkpoints.

## Estado encontrado

Claims y evidencia exacta, FTS, candidatos, revisiones de notas e intenciones recuperables
ya existen. La UI actual es Tkinter/ttk. Hay cambios locales anteriores a esta evolución.
No se modifican contratos Broker ni se cambia el framework UI.

## Secuencia y evidencia requerida

| Fase | Entrega | Checkpoint |
|---|---|---|
| 9 | Entidades, vigencia, sucesiones, histórico y reconciliación | Migración de datos existentes, pruebas de transición y recuperación, unittest/ruff/mypy |
| 10 | API v1 documental y de conocimiento, permisos, búsqueda, query con evidencia, ingesta | Contratos, aislamiento current/history, insuficiencia y documentación |
| 11 | Fuentes y conectores extensibles, scheduler durable, deduplicación, backoff, configuración | Caída/reinicio, fuente caída independiente y cambios triviales |
| 12 | Impacto, propuestas explicadas, conflictos, publicación y reindexado | Escenarios positivos/negativos, evidencias, notas externas y recuperación |
| 13 | Centro de operaciones, explorador, fuentes, revisión masiva y flujos | Evaluación del stack, comprobación visual y funcional |
| 14 | Políticas versionadas, simulación, límites, kill switch y auditoría | Pruebas agresivas, manual_lock, resultados parciales e histórico de políticas |

Cada fase requiere actualizar su registro con resultados reales antes de avanzar.
Una prueba con Broker simulado no acredita una prueba real Plugin → Broker → Obsidian.
No habilitar autoaprobación global, migrar UI, destruir datos ni cambiar contratos públicos
sin la decisión humana exigida por la especificación.

## Diseño de fase 9

Migración aditiva 012, sin recrear tablas existentes. `status` conserva el contrato
operativo ACTIVE/SUPERSEDED/RETRACTED; `knowledge_state` es la vigencia consultable.
No se confunde CURRENT con verificación factual: significa vigente en el modelo local.
`valid_from` es el inicio de vigencia registrado por el sistema, no una fecha factual
deducida de la fecha de publicación de una fuente. Los legacy conservan created_at.
Una entidad puede aparecer en varios claims y un claim puede referirse a varias entidades.
La relación de sucesión enlaza claims sin borrar evidencia ni revisiones previas.

Archivos: migración 012, modelos de conocimiento, repositorio y servicio de conocimiento,
integración con repositorio semántico y runtime, pruebas de fase 9 y documentación.
La aprobación existente es el punto de integración para registrar una sucesión atómica.
La reconciliación detectará diferencias en las notas sin sobrescribir contenido humano.

## Registro de checkpoints

- Fase 9: checkpoint de núcleo superado; 174 pruebas, ruff y mypy pasan.
  Evidencia y limitaciones en `Phase_9_Knowledge_Core.md`.
- Fase 10: checkpoint local/API superado; 189 pruebas, ruff, mypy y HTTP loopback.
  Inferencia real pendiente por WinError 10013 al conectar con el Broker.
  Evidencia y alcance en `Phase_10_Knowledge_API.md` y `Knowledge_API.md`.
- Fase 11: núcleo/API/recuperación verificados; 210 pruebas (209 pasan, 1 omisión
  explícita de Tcl/Tk), ruff y mypy pasan. Red real y pantalla pendientes por entorno.
  Evidencia en `Phase_11_Source_Monitoring.md` y `Source_Monitoring.md`.
- Fase 12: núcleo/API superados; 231 pruebas (230 pasan, 1 omisión Tcl/Tk), ruff/mypy pasan.
  Evidencia, contrato de mantenimiento y límites en `Phase_12_Knowledge_Maintenance.md`
  y `Maintenance_Review.md`. Broker/pantalla reales pendientes por entorno.
- Fase 13: iniciada; explorador integrado con filtros, evidencia e histórico y lectura
  reconciliada en segundo plano. 236 pruebas (234 pasan, dos omisiones Tk), ruff/mypy pasan.
  Segundo incremento: pipeline navegable, operaciones transversales y revisión de
  conflictos; batería actual de 248 pruebas (246 pasan, dos omisiones Tk), ruff/mypy pasan.
  Revisión masiva, API/automatización y checkpoint visual todavía pendientes.
  Registro: `Phase_13_Knowledge_Operations_UI.md`.
- Fase 14: pendiente; no iniciada.
