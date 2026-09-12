# Estado vigente de Knowledge Orchestrator

Incremento 26, **12 de septiembre de 2026 — 0.3.2, modelo para tareas con esquema**. Las tareas
que exigen JSON conforme a schema (extracción de afirmaciones, comparación de evidencia,
embeddings y consultas fundamentadas) eligen ahora modelo por sí mismas:
`services/model_selection.py` descarta los que declaran `thinking`, los marcados
`incompatible`, los que están en cuarentena y los de un proveedor que la propia petición no
permite; toma el primero utilizable por orden alfabético y devuelve `None` —«que elija el
Broker»— cuando no hay candidato, que es el comportamiento anterior.

Motivo: contra el Broker real, la extracción sobre una nota publicada falló con
`SEMANTIC_CONTRACT_FAILED` («el Broker no devolvió JSON semántico estricto») porque el modelo
elegido en Ajustes razona y antepone su cadena de pensamiento. El modelo del perfil sigue
mandando en la redacción del apunte; esta elección solo afecta a las tareas con schema.

**Dos correcciones más, salidas de probarlo contra el Broker real:**
- El primer criterio («el primero por orden alfabético sin `thinking`») eligió `glm-ocr:latest`,
  un OCR de 1.1B: determinista e inservible para una tarea con esquema. Ahora se descarta lo
  especializado (OCR, código, embeddings, guardas, transcripción, difusión), se exige
  `completion`, se prefiere el que declara `tools` y el mayor que no pase de 40B —en local un
  modelo enorme convierte una tarea de apoyo en una espera larga—, y a igualdad, orden
  alfabético. Con el catálogo del usuario elige `granite4.1:30b`.
- La clave idempotente de los trabajos semánticos era fija (`semantic_extract_note_1`):
  reintentar la misma nota con otro modelo o presupuesto chocaba con la petición que el Broker
  ya conserva y moría con **HTTP 409** sin ejecutarse. Ahora incorpora una firma del contenido
  (prompt, esquema, modelo y presupuesto): mismo contenido, misma clave —el replay idempotente
  sigue igual—; contenido distinto, clave distinta.

**483 pruebas en 212,701 s, cero fallos**; Ruff y mypy de 151 archivos pasan. Ejecutable 0.3.2
regenerado. Validación contra el Broker real: publicación reproducida tres veces (última, nota
de 6989 caracteres en 181 s). El resultado de la extracción de afirmaciones con el modelo
seleccionado se registra en `User_Workflow_QA_2026-09-11.md`.

Incremento 25, **12 de septiembre de 2026 — 0.3.1, modelos que razonan**. Un documento real
falló con `INVALID_PROVIDER_RESPONSE` y `done_reason=length`: el modelo gastó su
`max_output_tokens` razonando y no llegó a responder. Cuatro cambios, todos en la aplicación:

1. **Catálogo útil.** `UiSnapshotService.models()` descarta los modelos que el propio Broker
   marcó `incompatible` o en cuarentena —se ofrecían los 149, incluido uno incompatible desde
   agosto— y etiqueta el resto en Ajustes: `gemma4:12b · razona · 262k contexto`.
2. **Reintento automático.** Al detectar el presupuesto agotado, `apply_status` reabre la tarea
   una sola vez con el doble de tokens (techo 16 000), clave idempotente nueva y evento
   `BROKER_BUDGET_RETRY`; la captura no cae a FALLIDO.
3. **Presupuesto por tipo de tarea.** Las tareas semánticas dejan de compartir el 4000 fijo:
   extracción 6000, comparación 4000, consulta 4000, embedding 2000 (`TASK_BUDGETS`).
4. **Explicación y prevención.** El fallo se lee sin jerga y dice dónde corregirlo; guardar un
   modelo que razona con menos de 2000 tokens pide confirmación.

**Además, dos fallos que descubrió el recorrido contra el Broker real:**
- «Reintentar» reenviaba la petición congelada al planificar, así que cambiar el modelo en
  Ajustes no surtía efecto y el reintento repetía el mismo fallo. `retry_failed_task` reescribe
  ahora modelo, temperatura y presupuesto con el perfil vigente del workflow.
- El Broker podía **sustituir el modelo elegido** por otro (respondió `nemotron-3.5-lightning:30b`
  en lugar del pedido, y también razona): el perfil guardaba `fallback_allowed` pero Ajustes no
  lo ofrecía. Nueva casilla «Usar solo el modelo elegido (sin sustituciones del Broker)», que
  viaja como `model_requirements.fallback_allowed` y `execution.selection.allow_substitution`.
  Sin esto, elegir bien el modelo no garantizaba nada.
El contrato del Broker no admite desactivar el razonamiento (`generation` solo acepta
temperature, max_output_tokens, seed y top_p, con validación `extra="forbid"`): un `think:false`
exigiría una versión nueva del contrato en AI_Broker.

**478 pruebas en 191,276 s, cero fallos**; Ruff y mypy de 150 archivos pasan. Ejecutable 0.3.1
regenerado. **Verificado contra el Broker real** (192.168.1.52:8765, contrato 2.10): de 149
modelos del catálogo, la aplicación ofrece 87 —descarta los incompatibles y en cuarentena, entre
ellos el que causó el fallo original—; elegido `gemma4:12b` desde el desplegable etiquetado y con
el presupuesto del perfil (8000), un documento recorrió «En cola del Broker → Procesando →
Completado» y se publicó una nota de 6885 caracteres en 122 s. Los dos intentos previos, con un
modelo incompatible y 1200 tokens, agotaron 8 y 15 minutos sin publicar. Detalle en
`User_Workflow_QA_2026-09-11.md`.

**Límite abierto (12-sep-2026).** La extracción de afirmaciones sobre esa nota falló con
`SEMANTIC_CONTRACT_FAILED` («El Broker no devolvió JSON semántico estricto»): las tareas
semánticas piden JSON conforme a schema y un modelo con razonamiento no lo entrega limpio. Sin
claims, la consulta fundamentada responde «evidencia insuficiente» y queda sin acreditar con
evidencia real; el caso sin evidencia sí está demostrado. Opciones a decidir: elegir
automáticamente un modelo sin `thinking` para las tareas con schema, tolerar un preámbulo
extrayendo el primer objeto JSON, o pedir al Broker un control de razonamiento en el contrato.

Incremento 24, **11 de septiembre de 2026 — interfaz 0.3.0**. Rediseño aprobado por el
usuario a partir de maquetas: navegación lateral agrupada (Trabajo, Conocimiento, Sistema)
con contadores y Ctrl+1…0; Inicio con indicadores, recorrido del conocimiento en nodos,
atención y actividad reciente; Documentos con pasos del recorrido y fases en lenguaje de
usuario; Revisión con «Ahora/Propuesto»; Biblioteca con temas, vista previa verificada por
hash y apertura en Obsidian; tema oscuro también en paneles ttk y diálogos. Corregidos: Ajustes
ensanchaba la ventana a 2560 px; posición interna `2147483647` visible en Organización.
Aborto `Tcl_AsyncDelete` reproducido (2 de 3 con dos pruebas de ventana más
`test_reversion_ui`): la ventana destruida quedaba en ciclos que el recolector liberaba en otro
hilo. `DashboardBase.destroy` libera ahora en el hilo de Tk y `tools/verify_desktop.py` recoge
basura en el hilo principal tras cada prueba. `build_windows.ps1` pasaba `--add-data` relativo a
`--specpath` y no encontraba las migraciones; corregido y ejecutable 0.3.0 generado y arrancado
sobre raíz de ensayo. **470 pruebas en 185,232 s, cero fallos**; Ruff y mypy de 150 archivos pasan.

**Recorrido de usuario (12-sep-2026), raíz de ensayo aislada:** 26 de 27 pasos correctos con la
ventana y los workers reales; el único no ejecutado ahí fue la consulta al Broker. Detalle y
límites en `User_Workflow_QA_2026-09-11.md`. Defectos encontrados durante el recorrido y
corregidos: el estado del Broker nunca se actualizaba en la interfaz (el worker solo emite sus
eventos de salud por el puente y el resumen leía SQLite: figuraba siempre «sin comprobar»);
a 1080×680 quedaban fuera de la ventana acciones de Revisión y de Documentos; el refresco
automático de Ajustes descartaba los cambios de perfil sin guardar; mensajes técnicos en el pie
(«Ingestion result: capture_id ya registrado», «$: falta la apertura del frontmatter YAML») y un
error de validación en inglés. Cada uno con su regresión en `test_ui_redesign.py`.

Incremento 23, verificado localmente el **11 de septiembre de 2026**: arranque diferido del
escritorio con inicialización Tcl para Python 3.14.0/Windows. Se corrigieron el espacio
útil de la comparación de automatizaciones y las referencias/callbacks retenidos al
cerrar el escritorio. Las 70 pruebas de los cinco módulos de UI pasan en 39,196 s,
incluidas las cinco nativas antes omitidas. Tras las correcciones de cierre, la
regresión completa pasa: **454 pruebas en 325,693 s, cero fallos y cero omisiones**.
Ruff y mypy de 150 archivos pasan. Se usa `tools/verify_desktop.py`, que inicializa
Tcl por la misma ruta que el escritorio antes de descubrir las pruebas. La primera
ejecución con Tk activo terminó anormalmente y se conserva como evidencia del fallo
previo. Detalle y comando en `Phase_14_Automation_Governance.md`.

**Conexión de ensayo:** la captura más reciente de Obsidian muestra el puente
escuchando en 8766, y una consulta sin clave recibe HTTP 401. Queda configurar la
conexión autenticada en el Orchestrator y confirmar su apertura en el escritorio.

Verificación anterior al incremento 23, **11 de septiembre de 2026**: 452 pruebas Python en
256,941 s (447 pasan, cinco omisiones Tcl/Tk), Ruff y mypy de 149 archivos correctos.
Incremento 22: lectura de notas sin normalizar CRLF; cuatro regresiones comprueban
ediciones en base/resultado/evidencia y aprobación/reversión exacta de notas CRLF.
La integración usa un editor simulado; el recorrido real sigue pendiente.

Las 14 pruebas Node del incremento anterior pasan. Incremento 21: API conserva 8766 y puentes nuevos
usan 8767. Puertos/conexiones existentes se conservan. Ajustes sugiere el puerto del
plugin de la bóveda si no hay conexión válida guardada; Servicios propone un puerto
API distinto. La copia de ensayo sigue en 8766 y el usuario confirmó el paquete 0.1.2.
El aviso inicial de secreto inválido quedó superado: la última captura muestra escucha
activa y se obtuvo HTTP 401 sin credencial. La conexión autenticada sigue pendiente.

El incremento 20 convierte los fallos de lectura/codificación de notas en conflictos
durables durante aprobación/recuperación; conserva archivos y snapshots y continúa
con otras operaciones. Cuatro regresiones nuevas fallaban antes del cambio y pasan
después. No convierte las notas copiadas ni acredita el recorrido real pendiente.

Revisión del núcleo, API, fuentes, mantenimiento y gobernanza: **9 de septiembre de 2026**.
Las capacidades anteriores conservan su revisión del 23 de agosto; consultar las
limitaciones de evidencia real y los registros `Phase_9_Knowledge_Core.md` y `Phase_10_Knowledge_API.md`.

Este documento prevalece para cuestiones de estado y compatibilidad. `README.md` explica
el uso; `System_Architecture.md` y `Data_Contracts.md` contienen el diseño; los documentos
`Phase_*` son registros históricos de cada entrega.

**Ensayo local de Obsidian (9-sep-2026):** ya es accesible la copia facilitada por el
usuario. Se prepararon el puente desactivado y cinco notas ficticias, conservando por
hash los 140 archivos anteriores examinados. Ocho de las diez notas visibles existentes
no son UTF-8 válido y la base copiada contiene cero notas registradas. El runtime no se
inició ni se migró esa base. Esta preparación no acredita ejecución en Obsidian ni cierra
los escenarios reales; detalle en `docs/Obsidian_Trial_Checkpoint.md`.

**Puente 0.1.1 (11-sep-2026):** añade estado permanente y reintento, aclara nombre/valor
del secreto y solo muestra escucha tras el evento real del servidor. Catorce pruebas
Node pasan (cuatro nuevas), con host Obsidian sustituido y transporte local real.
Paquete copiado al ensayo conservando configuración/recibos; requiere recarga del
complemento. Las capturas previas prueban el panel 0.1.0 en Obsidian 1.13.7. La conexión
real aún devuelve WinError 10061 y el cliente de ensayo aún no tiene credencial guardada.

## Responsabilidad

Knowledge Orchestrator convierte capturas y documentos locales en conocimiento publicado
y revisable. Posee la validación de entrada, clasificación, perfiles, prompts, chunking,
workflow, claims, comparación semántica, revisión humana y proyección a Obsidian. AI Broker
solo ejecuta las tareas técnicas que recibe; no conoce el vault ni la semántica del
workflow.

## Flujo durable

```text
inbox -> estabilidad -> validación v1 -> staging + SHA-256 + SQLite
      -> processing -> clasificación -> workflow -> tareas AI Broker
      -> validación de resultados -> publicación atómica -> completed
                                      └-> claims y candidatos de revisión
```

No existe una transacción distribuida entre NTFS, SQLite, Broker y Obsidian. La consistencia
se obtiene con intenciones durables, claves idempotentes, temporales sincronizados,
reemplazos atómicos y reconciliación al arrancar.

## Capas actuales

- `domain`: contratos, estados y errores tipados.
- `repositories`: SQLite, migraciones y transiciones.
- `services`: ingesta, planificación, publicación, semántica y operaciones.
- `integrations`: cliente HTTP de AI Broker.
- `worker`: watcher, dispatcher, poller y trabajo fuera del hilo UI.
- `ui`: Tkinter/ttk, snapshots de solo lectura y puente de eventos al hilo principal.

## Compatibilidad Broker

El validador de dominio acepta las extensiones aditivas del contrato **2.10** y conserva
compatibilidad con respuestas 2.8 y 2.9.

**Deuda saldada (5-sep-2026).** El diagnóstico de `worker/broker_worker.py` comparaba la
capacidad anunciada con la cadena `"2.8"` y avisaba ante cualquier otra versión. Además de
convertir cada Broker nuevo en un aviso permanente —que el operador aprende a ignorar, y
entonces deja de servir para lo que existe—, la comparación por cadenas dice que `"2.10"`
es anterior a `"2.9"`. Ahora se compara contra `MINIMUM_CONTRACT_VERSION` por número
(`contract_at_least`), y solo avisa un Broker **por debajo** del mínimo. Cubierto por
`test_a_newer_contract_is_retained_without_a_warning` y
`test_a_contract_below_the_minimum_is_reported_as_warning`.

Del contrato 2.10 el orquestador usa:

- **`auxiliary_invocations: false`** (§8.4) cuando el perfil declara `confidential` o
  `local_only`. El sondeo en sombra del Broker respeta la clasificación de datos, pero
  «un modelo local» no es «el modelo que yo aprobé», y aquí se trabaja sobre notas del
  vault de su dueño. El cliente **retira** el campo si el Broker no anuncia el opt-out:
  la validación del Broker es `extra="forbid"`, así que pedir una garantía adicional a un
  Broker que no la tiene mataría la tarea entera con un 422.
- **`GET /tasks/{id}/invocations`** (§8.1) con `is_contractual_invocation`, que lee el
  booleano `contractual` y solo cae al nombre del rol contra un Broker anterior al 2.10.
- **`GET /tasks/{id}/artifacts`** (§8.3) con `final_artifact`, que filtra por `final` y no
  por `artifact_type`: la lista de tipos crece con cada estrategia nueva.

La autenticación no se presupone ni se descarta: `KO_BROKER_ADMIN_TOKEN` configura
`X-Admin-Token`. Sin token, el cliente omite la cabecera y solo funcionará si el despliegue
acepta ese acceso. Un 401/403 se trata como credencial rotada y recuperable.

## Capacidades implementadas

- watcher `watchdog` con rescan, estabilidad, cancelación y cuarentena;
- ingesta v1, deduplicación, recuperación y fuentes genéricas controladas;
- temas, perfiles versionados, prompts, chunking y síntesis;
- tareas Broker durables, polling, cancelación, modelos y estrategias configurables;
- publicación Obsidian con intención, hash y revisiones;
- extracción de claims, FTS5, embeddings opcionales, comparación, diff y aprobación;
- entidades y vínculos con claims, seis estados explícitos de vigencia, sucesiones e
  histórico de decisiones inmutable (migración aditiva 012);
- consultas current/historical/all, revisión optimista de estado y reconciliación
  documental al arrancar, sin sobrescribir ediciones humanas;
- API local v1 autenticada, documentos/revisiones, entidades/claims, búsqueda FTS/vectorial,
  consultas IA durables con citas exactas e ingesta controlada (`docs/Knowledge_API.md`);
- fuentes Web/RSS/Atom con configuración versionada, scheduler durable, hashes por ítem,
  backoff, revisión de novedades y entrega idempotente al flujo documental;
- mantenimiento: propuestas versionadas con impacto/riesgos/procedencia, edición y
  decisiones optimistas, contradicciones explícitas, sucesor en la nota destino,
  histórico estructurado o snapshot, reindexado y reconciliación de evidencia derivada;
- validación de ambas notas antes de aplicar/recuperar, protección de claims solapados
  y de dependencias durante publicaciones y revisiones concurrentes;
- UI de Resumen, Documentos, Biblioteca, Conocimiento, Fuentes, Revisión, Organización
  y Ajustes; explorador de claims con filtros de vigencia/entidad/texto, evidencia,
  sucesiones e histórico, con reconciliación documental en segundo plano;
- Operaciones: pipeline navegable, novedades de todas las fuentes, análisis y propuestas,
  filtros de incidencias, histórico de decisiones y lectura de la revisión anterior;
  accesos al documento, fuente y revisión individual, incluidos conflictos;
- backup SQLite, diagnóstico saneado y empaquetado Windows.
- revisión por lotes con planes inmutables, confirmación humana, selección o todas
  las pendientes, resultados parciales, recuperación y API con aislamiento de consumidor;
  comparación antes/después e historial de lotes en UI, con I/O fuera del hilo Tk.
- Servicios: listener API local controlado desde la sesión, consumidores y permisos
  sin credenciales visibles, actividad acotada y estado de vigilancia/análisis/lotes;
  pruebas HTTP reales de loopback para autenticación, permisos, cierre y reinicio.
- gobernanza inicial: políticas con ámbito explícito/versiones, decisiones auditables,
  control global pausado y simulación durable sin publicaciones (migración 017).
  Ejecutor de dominio con cupos diarios y por ejecución, autorización transaccional,
  recuperación y recibos implementado (migración 018). Planificador periódico conectado
  al runtime (migración 019), con arrendamientos, páginas, planes deduplicados y errores
  recuperables. Controles de políticas y auditoría por API con permiso `governance`
  implementados: creación/edición, simulación idempotente, autorización ligada a la
  simulación revisada y pausa versionada (migración 020). UI de políticas integrada en
  Servicios: configuración, simulación por páginas, autorización, pausa independiente
  e historial. Lógica verificada; render pendiente. La revisión independiente del
  puente propuesta/política y sus correcciones no deja hallazgos materiales. Reversión
  conservadora de dominio implementada (migración 021), con planes, reservas, decisión
  explícita, revisiones preservadas y recuperación. API de reversión con permiso review,
  planes propios por consumidor y recibos; UI Revisión → Publicaciones y reversión con
  comparación, motivo y auditoría. Revisión independiente de este incremento sin
  correcciones pendientes; render nativo aún no acreditado.
  Guías: `Automation_Governance.md` y `Maintenance_Reversion.md`.
  Navegación de políticas/fuentes/historial corregida ante lecturas fallidas, borrador
  e identidad conservados y simulaciones siguientes idempotentes tras respuesta perdida.
  Prompts de extracción/comparación con instrucciones de fuente explícitamente
  no autorizantes y delimitadores JSON protegidos; pruebas adversarias de documento,
  contratos, manual_lock, confianza y ausencia de publicación no autorizada.
  Evaluar con política conecta la revisión individual con una simulación de la propuesta
  y revisión exactas; preserva borradores y snapshots históricos. Los assessments nuevos
  distinguen evaluación de política pendiente de elegibilidad real. Un registro histórico
  de otra propuesta/revisión no permite autorizar con el filtro activo.
  Transiciones de análisis y propuestas auditadas en la misma transacción, incluidos
  reintentos/recuperación, intención y conflictos. Publicación enlazada a actor,
  revisión, lote/ejecución y sucesor. Eventos nuevos sin texto de documentos/errores
  remotos y sin duplicados por repetición de estados. Matriz de campos y trazabilidad
  en `Proposal_Audit_Evidence.md`.
  Ver trazabilidad desde Revisión y Propuestas/Histórico de decisiones permite recorrer
  versiones, comparación, evidencia, tareas/modelos reportados y decisión/publicación.
  Distingue las simulaciones de ejecución y autorización, sus actores/fechas originales,
  y la reversión posterior. Lecturas en segundo plano con selección estable incluso
  al entrar nuevas revisiones. Revisión independiente sin hallazgos materiales pendientes;
  render nativo y recorrido visual integral todavía no acreditados.
  Registros y diagnóstico reforzados: cabeceras completas, JSON textual y token Broker
  configurado en memoria; exportación de líneas completas sin reescribir logs. Errores
  YAML con causa/posición sin snippets en evento/sidecar/traceback; original conservado.
  Actividad de workflows con avisos agregados, número de citas sin respaldo y código
  permitido de fallback; texto/URLs remotos no se duplican en estos eventos nuevos.
  Inventario `Delivery_Acceptance_Audit.md`: 65 entregas de fase, 16 criterios globales,
  objetivos, contratos/campos, rutas, guardas y gates con evidencia y pendientes.
  Guarda de fecha sola verificada: evidencia antigua, observación posterior sin cambio
  e inferencia por fecha sin cita no autorizan reemplazo, incluso con política aprobada,
  avance del reloj de planificación y reinicio. Notas, claims e histórico conservados.
  Cliente Broker sanea errores HTTP/de conexión y objetos de error antes de persistirlos,
  usando credenciales de la petición y configuración vigente. Pruebas de rotación,
  persistencia semántica/workflow y reintento; sin reescribir históricos ni resultados.
  Publicación inicial sin sustituir destinos ocupados: conflicto durable y recuperación
  que conserva la edición humana y continúa otras notas. Prueba con escritor separado
  en la carrera de instalación y caída con enlace residual. Requiere volumen con enlaces
  duros; no cierra la ventana check/replace de mantenimiento de notas existentes.
  Puente Obsidian integrado para el entorno confirmado por el usuario: Windows
  con bóveda local. Aprobación, recuperación y reversión usan el cliente; retirada
  la ruta de reemplazo directo. Sin puente, la intención queda pendiente; un conflicto
  de base/recibo requiere revisión. Ajustes permite guardar y comprobar conexión,
  con credencial DPAPI propia ligada a la bóveda. API devuelve 503 y estado pendiente.
  Batería general: 440 pruebas en 293,853 s (435 pasan, cinco omisiones Tcl/Tk).
  Después se añadió y verificó el caso API 503, dentro de diez pruebas focalizadas de
  conexión/integración. Diez pruebas Node pasan; Ruff/mypy pasan (149 archivos).
  Verificación final de API, integración y reversión: 40 casos pasan en 29,873 s,
  después de añadir el aviso API 503 y el mensaje de reversión pendiente.
  Evidencia en `Phase_14_Automation_Governance.md`.

## Límites y evidencia pendiente

- Auditoría inicial de los veinte escenarios en `Acceptance_Evidence.md`: caso 18
  cubierto por pruebas locales de fuente adversaria; resistencia de un modelo real
  pendiente. Explicación de elegibilidad corregida para propuestas nuevas y contextualizada
  sin reescribir snapshots históricos. Matriz de entregables/globales creada en
  `Delivery_Acceptance_Audit.md`; los requisitos parciales y checkpoints visuales siguen
  abiertos. Campos/categorías/reconstrucción documentados con pruebas;
  acceso a versiones/tareas/modelos/decisiones implementado en interfaz, con render y
  recorrido integral pendientes. Saneamiento de logs/ZIP y errores YAML reforzado;
  mensajes remotos persistidos por otras rutas anteriores y texto libre arbitrario
  aún no tienen una garantía global de anonimización.
  La prueba dedicada de fecha como único disparador pasa. El ensayo con otro proceso
  reprodujo sobrescritura después del último hash en el antiguo método de mantenimiento
  y reversión. Ese método se ha sustituido por el puente Obsidian. Bloqueos nativos simples no
  proporcionan aún una solución acreditada; TxF devolvió WinError 6832 al abrir el
  temporal del ensayo. Véase `Note_Replacement_Coordination.md`; el usuario confirmó
  Obsidian/Windows/local. La integración se verifica con un editor de ensayo explícito;
  falta instalar y probar el puente dentro de Obsidian. Este gate no está superado.
  Se preparó una bóveda temporal con cinco notas ficticias y el puente desactivado.
  Computer Use responde, pero rechazó abrir Obsidian: `Computer Use was not approved
  to use Obsidian`, también después de la autorización expresa del usuario para usar
  Obsidian y la bóveda de ensayo. Acceso efectivo pendiente; ejecución real sin acreditar. Evidencia
  y ubicación del ensayo en `Obsidian_Trial_Checkpoint.md`.

- Hay Web y RSS/Atom; no hay rastreo recursivo, GitHub releases ni búsqueda web autónoma.
- La evolución por fases 9–14 está en curso: fases 9 y 10 superan sus checkpoints locales;
  fase 11 verifica núcleo/API/recuperación, con pantalla y red pendientes por entorno.
  La fase 12 supera núcleo/API: 231 pruebas, 230 pasan y una omisión Tcl/Tk; ruff/mypy pasan.
  Primer incremento de fase 13: 236 pruebas, 234 pasan y dos omisiones Tcl/Tk; ruff/mypy
  pasan (110 archivos). El explorador está implementado; su render sigue sin verificar.
  Revisión por lotes: batería actual de 261 pruebas (258 pasan y tres omisiones Tk),
  ruff/mypy pasan (116 archivos). Detalle en `Phase_13_Knowledge_Operations_UI.md`.
  Centro de operaciones, revisión por lotes y estado API/automatizaciones en UI implementados;
  API/UI de reversión implementadas; checkpoints visuales y verificaciones externas siguen pendientes según
  `Knowledge_Lifecycle_Plan.md`.
- La descarga pública devuelve NETWORK_DENIED. La prueba visual de Fuentes no se ejecuta
  porque Tcl/Tk no inicializa init.tcl en este entorno. Véase `Phase_11_Source_Monitoring.md`.
- La consulta real al Broker desde el entorno de desarrollo está sin verificar: el socket
  saliente devuelve WinError 10013 antes de recibir HTTP. La API local sí pasó prueba HTTP.
- Sustituir conocimiento requiere revisión humana o autorización de una política
  aprobada y revalidada; `manual_lock` lo impide siempre. El planificador periódico
  respeta la pausa global y las políticas desactivadas por defecto. No se han autorizado
  políticas en los datos del usuario. La pausa evita nuevas intenciones; las iniciadas
  conservan su finalización/recuperación.
- Los embeddings son opcionales y no sustituyen la coincidencia exacta de spans.
- La prueba integral real Plugin -> Orchestrator -> Broker -> Obsidian debe ejecutarse y
  archivarse como evidencia de release; las pruebas unitarias y de integración parcial no
  demuestran por sí solas el entorno completo.

## Verificación

```powershell
$env:PYTHONPATH = "src"
python -B -m unittest discover -s tests -v
python -m ruff check src tests
python -m mypy src
```
