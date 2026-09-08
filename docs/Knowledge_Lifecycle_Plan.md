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
  Tercer incremento: revisión masiva durable, comparación antes/después, recibos,
  recuperación y API de lotes implementados; batería final de 261 pruebas (258 pasan,
  tres omisiones Tk), ruff/mypy pasan (116 archivos). Cuarto incremento: Servicios con
  estado API, consumidores y procesos automáticos; 267 pruebas (264 pasan, tres omisiones
  Tk), ruff/mypy pasan (118 archivos). HTTP local real verificado; checkpoint visual
  y revisión independiente de este último incremento pendientes por entorno.
  Registro: `Phase_13_Knowledge_Operations_UI.md`.
- Fase 14: iniciada; migración 017, políticas explícitas/versionadas, decisiones,
  control global pausado y simulación durable. Diez pruebas propias pasan; ruff/mypy
  pasan (121 archivos). Ejecución/cupos diarios/recuperación, reversión y controles de
  políticas API/UI pendientes. Ninguna política habilitada en datos del usuario.
  Batería completa actual: 277 pruebas (274 pasan, tres omisiones Tk), ruff/mypy pasan.
  Segundo incremento: ejecución/cupos reservados con intención, recuperación y recibos
  implementados (migración 018). 24 pruebas propias de gobernanza/ejecución pasan;
  ruff/mypy pasan (124 archivos). Planificador, controles API/UI y reversión pendientes.
  Batería final de este incremento: 291 pruebas (288 pasan, tres omisiones Tk).
  Tercer incremento: planificador conectado al runtime, migración 019, arrendamientos,
  paginación y deduplicación durables. Quince pruebas nuevas pasan y ruff/mypy pasan
  en 127 archivos. Controles API/UI y reversión siguen pendientes. La autoaprobación
  permanece pausada por defecto; ninguna política habilitada en datos del usuario.
  Batería completa del tercer incremento: 306 pruebas en 103,711 s (303 pasan y tres
  omisiones Tcl/Tk), ruff/mypy pasan en 127 archivos.
  Cuarto incremento: API de políticas/control/auditoría con permiso `governance`,
  simulación idempotente y autorización ligada al plan revisado (migración 020).
  Doce pruebas nuevas pasan, incluida pausa por HTTP real de loopback. Batería completa:
  318 pruebas en 113,597 s (315 pasan, tres omisiones Tcl/Tk); ruff/mypy pasan en 132 archivos.
  Controles visuales y reversión conservadora siguen pendientes.
  Quinto incremento: controles de políticas integrados en Servicios con configuración,
  fuentes entre páginas, simulación de 1–100 propuestas, autorización explícita,
  pausa independiente y auditoría. Doce pruebas nuevas, once pasan y una omisión Tk.
  Batería completa: 330 pruebas en 121,010 s (326 pasan, cuatro omisiones Tcl/Tk);
  ruff/mypy pasan en 136 archivos. Sin migración adicional ni activaciones en datos
  del usuario. Render pendiente por Tcl/Tk y revisión independiente pendiente por
  límite de uso del revisor. Reversión conservadora aún pendiente.
  Sexto incremento: reversión conservadora de dominio y recuperación implementadas,
  migración 021, planes/decisiones inmutables, reservas y preservación de revisiones,
  vigencia y recibos. Diecinueve pruebas nuevas pasan. Batería completa final:
  349 pruebas en 132,871 s (345 pasan, cuatro omisiones Tcl/Tk); ruff/mypy pasan
  en 139 archivos. Acceso API/UI y recibos visuales de reversión aún pendientes.
  Guía y condiciones: `Maintenance_Reversion.md`. Ningún documento del usuario revertido.
  Séptimo incremento: cinco rutas de reversión con permiso review y aislamiento de
  consumidor; Revisión → Publicaciones y reversión con comparación, confirmación y
  recibos. Auditoría local de todos los actores, confirmación solo de planes propios.
  Diecisiete pruebas nuevas: 16 pasan y una omisión Tk. Batería completa final:
  366 pruebas en 169,196 s (361 pasan, cinco omisiones Tcl/Tk); ruff/mypy pasan
  en 142 archivos, diff sin errores. Revisión independiente de este incremento
  sin correcciones pendientes; render, revisiones anteriores e integración externa
  conservan las limitaciones documentadas. Sin nueva migración ni cambios en notas del usuario.
  Octavo incremento: páginas resistentes a errores en políticas/fuentes/historial,
  conservación de borrador/identidad, claves estables al reintentar simulaciones
  siguientes y foco de teclado corregido. Seis pruebas nuevas pasan. Batería final:
  372 pruebas en 180,910 s (367 pasan, cinco omisiones Tcl/Tk); ruff/mypy pasan en
  142 archivos y diff sin errores. Auditoría inicial de los veinte escenarios en
  `Acceptance_Evidence.md`: caso 18 parcial, pendiente de prueba adversaria de fuente.
  Revisor de Servicios/políticas sigue pendiente por cuota; render e integración
  externa no acreditados. El checkpoint global permanece abierto.
  Noveno incremento: instrucciones y delimitadores reforzados para fuentes no
  confiables en extracción/comparación/embeddings; cinco pruebas adversarias nuevas
  pasan y la prueba previa comprueba el texto decodificado exacto. Batería final:
  377 pruebas en 176,952 s (372 pasan, cinco omisiones Tcl/Tk); ruff/mypy pasan
  en 142 archivos y diff sin errores. Sin migración ni cambio de contrato Broker.
  Caso 18 verificado en barreras locales, modelo real pendiente. Próximo hallazgo:
  explicación fija de ausencia de política en assessment frente a evaluación real
  de gobernanza; conservar snapshots históricos al resolverlo.
  Décimo incremento: explicación de evaluación por políticas corregida en propuestas
  nuevas y contexto vivo separado de snapshots inmutables. Revisión → Evaluar con
  política conserva candidato/revisión exactos y borrador; historial ajeno no habilita
  autorización con filtro. Comparación desplazable con altura mínima y foco visible.
  Siete pruebas nuevas pasan; batería completa: 384 pruebas en 194,926 s (379 pasan,
  cinco omisiones Tcl/Tk). Ruff/mypy pasan sobre 142 archivos y diff sin errores.
  Revisión independiente de este incremento sin hallazgos materiales pendientes.
  Sin nueva migración ni uso/persistencia del token real. Render, integración externa
  y auditoría completa de campos/eventos/entregables siguen pendientes.
  Undécimo incremento: eventos transaccionales de trabajos/candidatos e intención,
  conflictos derivados y atribución de publicación. Siete pruebas nuevas; caso de
  procesador existente ampliado con campos, tareas/modelos reportados y snapshot
  conservado. Matriz `Proposal_Audit_Evidence.md` cubre 19 campos, 12 categorías
  de observabilidad y 10 preguntas de reconstrucción, distinguiendo límites.
  Batería completa: 391 pruebas en 195,176 s (386 pasan, cinco omisiones Tcl/Tk);
  ruff/mypy pasan en 142 archivos y diff sin errores. Sin nueva migración ni cambios
  de contratos. Acceso visual integral a auditoría, saneamiento de errores anteriores,
  inventario global de entregables, render e integración externa siguen pendientes.
  Duodécimo incremento: Ver trazabilidad desde Revisión y Propuestas/Histórico,
  con versiones paginadas, comparación, evidencia, tareas/modelos reportados y
  decisión/lote/política/reversión. La revisión fija se recoloca ante nuevas versiones;
  la simulación de ejecución y la revisada al autorizar se distinguen con actor/fecha.
  Ocho pruebas nuevas pasan; nativa y procesador existentes ampliados. Batería final:
  399 pruebas en 143,502 s (394 pasan, cinco omisiones Tcl/Tk); ruff/mypy pasan
  en 145 archivos y diff sin errores. Revisión independiente sin hallazgos pendientes.
  Sin migración ni cambios API/Broker. Render/recorrido integral, inventario global,
  saneamiento de errores antiguos e integración externa siguen abiertos.
  Decimotercer incremento: saneamiento de cabeceras completas, JSON textual anidado,
  credenciales URL y token Broker configurado en memoria. Diagnóstico con líneas
  completas, sin reescritura de logs; YAML con causa/posición sin snippets en errores,
  eventos ni sidecars, conservando el original rechazado. Nueve pruebas nuevas;
  batería completa: 408 pruebas en 175,091 s (403 pasan, cinco omisiones Tcl/Tk).
  Ruff/mypy pasan en 145 archivos y diff sin errores. Sin migración ni uso del token
  real. No se garantiza anonimización de texto libre ni de otros mensajes remotos
  persistidos anteriormente. Inventario global, render y flujo externo pendientes.
  Decimocuarto incremento: inventario de 65 entregas y 16 criterios globales, objetivos,
  contratos/campos, rutas, guardas y gates en `Delivery_Acceptance_Audit.md`. Eventos de
  avisos/citas/fallback sin duplicar texto remoto, con enlaces/contadores/código permitido.
  Tres pruebas nuevas; batería: 411 pruebas en 176,656 s (406 pasan, cinco omisiones Tk).
  Ruff/mypy pasan (145 archivos), diff sin errores. Sin migración. Quedan pendientes
  fecha como único disparador, persistencia remota restante y pruebas de editor/render/red.
  Decimoquinto incremento: guarda de fecha sola verificada con política autorizada,
  fuentes/archivos temporales, avance del reloj del planificador y reinicio. Evidencia
  antigua, observación posterior sin cambio e inferencia de reemplazo sin cita no
  modifican notas/claims/historial ni crean reservas/publicaciones. Tres pruebas nuevas;
  batería: 414 pruebas en 220,593 s (409 pasan, cinco omisiones Tk). Ruff/mypy pasan
  (145 archivos), diff sin errores. Sin migración ni cambios en guardas de producción.
  Próximo punto: credenciales en errores Broker y reconfiguración. Render/red/editor
  real y checkpoint global siguen abiertos.
  Registro: `Phase_14_Automation_Governance.md`.
