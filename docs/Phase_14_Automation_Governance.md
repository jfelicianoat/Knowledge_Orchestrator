# Fase 14 — Automatización y gobernanza

## Incremento 18 en curso: coordinación con Obsidian (9 de septiembre de 2026)

1. **Estado encontrado.** Ensayo reproducible con otro proceso confirma pérdida de
   una edición entre último hash y replace. Se corrigió el inventario: hay evidencia
   contradictoria, no solo un ensayo pendiente. Bloqueos simples impiden el reemplazo
   propio o permiten renombrados compartidos; TxF devuelve WinError 6832 en el ensayo.
2. **Diseño.** El usuario confirma Obsidian/Windows/bóveda local. Se elige un puente
   con `Vault.process()`: la decisión y autorización siguen en el Orchestrator.
3. **Cambios.** Plugin, servidor loopback autenticado, validación de base dentro del
   callback, journal sincronizado e idempotencia ante respuesta perdida. Cliente Python
   verifica recibo, bóveda y archivo posterior. No hay integración de runtime todavía.
4. **Archivos.** `obsidian-bridge/`, `integrations/obsidian_bridge.py`, su test Python,
   `tools/probe_note_replacement.py` y documentación de coordinación/aceptación.
5. **Migraciones.** Ninguna. Sin instalación, activación ni cambios de bóveda real.
6. **Tests.** Diez Node (callback simulado, archivos/transporte reales); seis Python.
   El journal inicialmente usaba un handle append incompatible con truncar en Windows;
   corregido a apertura de lectura/escritura, con creación exclusiva si falta.
7. **Verificación.** Diez Node y seis Python pasan; syntax check del plugin, Ruff y
   mypy (147 archivos) pasan. Batería completa registrada al terminar la ejecución.
8. **Riesgos/deuda.** Callback aún no probado dentro de Obsidian. Faltan conexión
   protegida, enlace a aprobación/recuperación/reversión y retirar reemplazo directo.
   La ruta existente conserva el defecto hasta integrar el puente.
9. **Checkpoint.** En curso; ninguna afirmación de cierre de la guarda ni del proyecto.
10. **Próximo paso.** Integrar la conexión y las intenciones existentes con el cliente,
    conservando idempotencia, conflictos y revisión de resultados ambiguos.

Verificación de componentes del incremento 18: **431 pruebas Python en 188,548 s;
426 pasan y cinco omisiones Tcl/Tk**. Diez pruebas Node adicionales pasan; sintaxis
del plugin correcta. Ruff/mypy pasan (147 archivos de producción), diff sin errores.
El resultado no cierra el defecto de la ruta legacy ni acredita Obsidian real.

## Decimoséptimo incremento: destino ocupado al publicar (8 de septiembre de 2026)

1. **Estado encontrado.** La publicación inicial usaba `os.replace`: si el destino
   tenía contenido distinto, también durante recuperación tras una caída, lo sustituía.
2. **Diseño.** Instalar el archivo nuevo completo sin reemplazar un destino ocupado,
   conservar intención/fuente y registrar el conflicto sin bloquear otras notas.
3. **Cambios.** Instalación mediante enlace duro del temporal sincronizado, que falla
   si el destino apareció entretanto. Nota `CONFLICT` y error `PUBLICATION_CONFLICT`
   visible en la captura; evento único por transición. Recuperación reexamina conflictos;
   si el usuario conserva la edición en otra ruta, puede completar la intención original.
   Un temporal residual se desvincula antes de escribir para no modificar otra ruta
   que aún comparta su archivo tras una caída y un movimiento externo.
4. **Archivos.** `services/publication.py`, `repositories/publication_repository.py`,
   `tests/test_publication_conflicts.py` y documentación de publicación/estado/aceptación.
5. **Migraciones.** Ninguna: el estado textual de notas ya admite `CONFLICT`.
6. **Tests.** Seis nuevos: destino ocupado, carrera con escritor en otro proceso,
   edición después de caída, enlace residual después de movimiento, continuidad de
   otras publicaciones e idempotencia sin temporal. Fuentes y edición humana conservadas.
7. **Verificación.** 13 pruebas focalizadas pasan en 5,747 s; Ruff y mypy pasan
   (146 archivos). Resultado de batería completa registrado debajo.
8. **Riesgos/deuda.** El volumen debe admitir enlaces duros; si no, falla conservando
   la intención, sin degradar a sobrescritura. Esto cubre creación de notas nuevas;
   la ventana check/replace de actualizaciones semánticas y reversión sigue abierta.
   Escritor de prueba independiente no equivale a recorrido real con Obsidian.
9. **Checkpoint.** Conflicto de publicación inicial verificado localmente;
   gate global de convivencia con editor externo aún abierto.
10. **Próximo paso.** Resolver coordinación para sustituir notas existentes y completar
    los gates nativos/externos cuando el entorno lo permita.

Verificación completa final del incremento 17: **425 pruebas en 255,751 s;
420 pasan y cinco omisiones explícitas Tcl/Tk**. Ruff/mypy pasan (146 archivos);
`diff --check` pasa. Sin uso del token real ni cambios en documentos del usuario.

La investigación siguiente debe distinguir renombrado y coordinación de acceso:
Microsoft documenta que `FILE_RENAME_POSIX_SEMANTICS` puede sustituir un archivo con
handles abiertos, que siguen apuntando al anterior; eso por sí solo no demuestra
una comparación condicional de contenido. Los oplocks son otra API con protocolo
de adquisición/ruptura que necesita un ensayo propio. Fuentes primarias consultadas:
[FILE_RENAME_INFORMATION](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/ns-ntifs-_file_rename_information)
y [tipos de oplocks](https://learn.microsoft.com/en-us/windows/win32/fileio/types-of-opportunistic-locks).
No se ha implementado ni certificado esa coordinación en este incremento.

## Decimosexto incremento: credenciales en errores Broker (8 de septiembre de 2026)

1. **Estado encontrado.** El formateador de logs ocultaba secretos demasiado tarde
   para errores que ya se habían guardado en tareas y trabajos semánticos.
2. **Diseño.** Compartir el saneamiento entre diagnóstico y cliente Broker; usar la
   credencial enviada en cada petición y la configuración vigente, solo en memoria.
3. **Cambios.** Errores HTTP, mensajes de conexión y objetos `error` de respuestas JSON
   se sanean antes de propagarlos. Una respuesta anterior a la rotación conserva su
   contexto de credencial. El traceback visible no recupera la causa de red sin sanear.
   Se conservan clasificación HTTP, códigos convencionales y reintentos de autenticación.
4. **Archivos.** `redaction.py`, `integrations/broker_client.py`, `services/operations.py`,
   `tests/test_broker_error_privacy.py` y documentación de aceptación/estado/checkpoint.
5. **Migraciones.** Ninguna; no se reescriben datos históricos ni configuración del usuario.
6. **Tests.** Cinco nuevos: matriz HTTP y variantes de respuesta, traceback de conexión,
   respuesta tardía con rotación y autenticación posterior, persistencia de errores en
   workflow/trabajo semántico, y reintento durable ante 503. Solo credenciales ficticias.
7. **Verificación.** 36 pruebas específicas pasan en 4,606 s; Ruff y mypy pasan sobre
   146 archivos de producción. Resultado de batería completa registrado debajo.
8. **Riesgos/deuda.** No anonimiza contenido de resultados, texto privado arbitrario ni
   históricos. Prueba de Broker real, render nativo y editor externo siguen pendientes.
9. **Checkpoint.** Protección en la frontera de error verificada localmente;
   objetivo global abierto.
10. **Próximo paso.** Revisar la guarda de publicación frente a edición externa y
    completar los gates visuales/de integración cuando el entorno permita ejecutarlos.

Verificación completa final del decimosexto incremento: **419 pruebas en 187,072 s;
414 pasan y cinco omisiones explícitas Tcl/Tk**. Ruff/mypy pasan (146 archivos);
`diff --check` pasa. Token real nuevo no utilizado; prueba externa sigue pendiente.

## Decimoquinto incremento: una fecha no autoriza cambios (8 de septiembre de 2026)

1. **Estado encontrado.** La auditoría identificó falta de evidencia específica de la
   guarda temporal. `source_date` y `observed_at` son datos de evidencia; no hay un
   temporizador de caducidad que autorice sustituciones. El planificador selecciona
   propuestas revisables y exige la evaluación de la política.
2. **Diseño.** Probar el comportamiento público con notas fechadas, fuentes oficiales
   simuladas y política expresamente autorizada sobre datos temporales. Avanzar reloj
   del planificador y reconstruir/reconciliar runtime para comprobar recuperación.
3. **Cambios.** Evidencia de que el paso del tiempo no crea propuestas/publicaciones,
   una observación posterior de texto idéntico no autoriza parche y un reemplazo
   inferido solo por fecha se rechaza sin versión parcial. Guardas existentes conservadas.
4. **Archivos.** `tests/test_temporal_authorization.py` y documentación de aceptación,
   inventario, gobernanza, estado y checkpoint.
5. **Migraciones.** Ninguna; pruebas sobre bases y archivos temporales.
6. **Tests.** Tres casos nuevos con snapshots de notas/claims/candidatos/historial;
   ausencia de revisiones de nota, ejecuciones y reservas. Comparación inválida deja
   cero versiones de propuesta. Se comprueban tres ciclos con reinicio intermedio.
7. **Verificación.** Tres pruebas pasan en 3,092 s. Mypy pasa sobre 145 archivos;
   se corrigió una línea de test que excedía el máximo de ruff en un carácter.
   Resultado final de batería/calidad registrado debajo.
8. **Riesgos/deuda.** Estas fechas no equivalen a verificación factual ni a una política
   nueva de vencimientos. No se acredita obediencia de un modelo real. Persisten gates
   de render, red, editor externo y revisión de persistencia de mensajes remotos.
9. **Checkpoint.** Guarda temporal verificada localmente; objetivo global abierto.
10. **Próximo paso.** Proteger credenciales en las fronteras de error del cliente Broker,
    revisando también reconfiguración y conservación de la clasificación de reintentos.

Verificación completa final del decimoquinto incremento: **414 pruebas en 220,593 s;
409 pasan y cinco omisiones explícitas Tcl/Tk**. Ruff/mypy pasan sobre 145 archivos;
`diff --check` pasa. Objetivo y checkpoint global abiertos.

## Decimocuarto incremento: inventario global y actividad mínima (8 de septiembre de 2026)

1. **Estado encontrado.** Las matrices anteriores cubrían escenarios/campos, pero no
   las 65 entregas de fase ni los 16 criterios globales. Los avisos, URLs citadas sin
   respaldo y fallos de consenso se duplicaban como texto remoto en eventos de actividad.
2. **Diseño.** Inventariar requisitos contra contratos/productores/aserciones, separando
   evidencia local, parcial y real. Eventos mínimos con enlaces y contadores; detalle
   original conservado en el registro de tarea, sin cambiar decisiones de ejecución.
3. **Cambios.** `Delivery_Acceptance_Audit.md` relaciona entregas, objetivos, campos,
   rutas, guardas y checkpoints. Eventos de avisos agregados por tarea; citas sin
   respaldo solo cuentan enlaces; fallback conserva exclusivamente su código permitido.
4. **Archivos.** `workflow_repository/estado.py`, `test_workflow_audit_privacy.py`,
   inventario nuevo y documentación de estado/auditoría/checkpoint.
5. **Migraciones.** Ninguna; no se reescriben eventos ni respuestas históricas.
6. **Tests.** Tres nuevos: eventos sin texto/URLs y terminal idempotente, fallback
   permitido/prohibido sin alterar decisión y rollback cuando falla la escritura del
   evento. La importación inicial hacía descubrir diez tests ajenos; corregida para
   contar solo los tres nuevos, sin inflar la batería.
7. **Verificación.** Tres pruebas en 1,375 s; batería completa **411 pruebas en 176,656 s:
   406 pasan y cinco omisiones Tcl/Tk**. Ruff/mypy pasan (145 archivos); diff sin errores.
8. **Riesgos/deuda.** Los detalles remotos de tareas y otras rutas siguen conservando
   texto libre; no se promete saneamiento universal. Inventario señala prueba específica
   pendiente de fecha sola, ventana check/replace, render e integración externa.
9. **Checkpoint.** Incremento local verificado; inventario realizado sin convertir
   los requisitos parciales o sin prueba real en cumplidos. Objetivo global abierto.
10. **Próximo paso.** Cubrir la guarda de fecha sola y revisar las rutas de persistencia
    remota restantes. Ejecutar gates visuales/externos cuando cambie el entorno.

## Decimotercer incremento: registros y diagnóstico (8 de septiembre de 2026)

1. **Estado encontrado.** El patrón de Authorization ocultaba el esquema Bearer pero
   dejaba la credencial. JSON textual y fragmentos de cola sin su clave podían eludir
   saneamiento. El parser YAML copiaba snippets de captura a error, sidecar y evento.
   La validación Markdown de publicación ya usa mensajes fijos: no se modificó.
2. **Diseño.** Reutilizar el formateador y exportador; interpretar JSON antes de sanear,
   ocultar cabeceras completas y token configurado en memoria, conservar solo líneas
   completas. Error YAML con causa/posición y sin traceback encadenado del parser.
3. **Cambios.** Redacción de asignaciones entrecomilladas, credenciales de URL, JSON
   anidado y secreto conocido literal/escapado/codificado. Límite de profundidad para
   no fallar al registrar estructuras excesivas. Exportación sin reescribir logs.
   Cuarentena conserva el original sin duplicar snippets en registros auxiliares.
4. **Archivos.** `services/operations.py`, `runtime.py`, `domain/contracts.py`, tests
   de operaciones/contratos/ingestión y documentación de operación/estado/auditoría.
5. **Migraciones.** Ninguna; no se borran logs, snapshots, históricos ni datos previos.
6. **Tests.** Nueve nuevos: cabeceras/asignaciones, JSON/rutas, token conocido en log
   y traceback, ZIP legado sin modificar origen, cortes de cola, límites exactos de
   línea, anidamiento excesivo, YAML sin snippets y rechazo durable sin duplicarlos.
   La prueba de ZIP existente ahora comprueba también ausencia del secreto ficticio.
7. **Verificación.** 32 pruebas focalizadas pasan en 7,382 s. Ruff/mypy pasan sobre
   145 archivos. Batería completa final registrada debajo. Se corrigió una referencia
   de test a `error_message`: el contrato existente usa `message`.
8. **Riesgos/deuda.** El saneamiento por patrón no garantiza anonimizar contenido
   libre arbitrario ni credenciales antiguas sin etiqueta. No se acredita saneamiento
   global de mensajes remotos persistidos en todos los repositorios anteriores. No se
   utilizó el token real, la red externa ni datos del usuario para estas pruebas.
9. **Checkpoint.** Protecciones locales implementadas; objetivo global abierto.
   Render, recorrido visual integral, inventario global y flujo real siguen pendientes.
10. **Próximo paso.** Completar matriz de entregables por fase y aceptación global;
    revisar los mensajes remotos persistidos que aún están fuera de esta protección.

Verificación completa final del decimotercer incremento: **408 pruebas en 175,091 s;
403 pasan y cinco omisiones explícitas Tcl/Tk**. Ruff/mypy pasan sobre 145 archivos;
`diff --check` pasa. Objetivo y checkpoint global abiertos.

## Duodécimo incremento: trazabilidad consultable desde la interfaz (8 de septiembre de 2026)

1. **Estado encontrado.** Las versiones, tareas/modelos y vínculos de decisión estaban
   en snapshots/tablas, pero no se podían recorrer desde la revisión de una propuesta.
2. **Diseño.** Extender Revisión y Propuestas/Histórico con un diálogo de consulta,
   conservando la identidad visual, el candidato fijo y la separación entre una
   revisión histórica y la decisión/publicación actual. Sin controles de escritura.
3. **Cambios.** Lector SQLite en una transacción de lectura; versiones paginadas de
   100 en 100, comparación, fuentes, tareas/modelos reportados, autor/fechas, lote,
   política y simulaciones, nota anterior y reversión. Lectura fuera del hilo UI,
   conservación de contenido/etiqueta ante error y reintento de la selección exacta.
4. **Archivos.** `services/proposal_audit.py`, `ui/proposal_audit_dialog.py`,
   `ui/proposal_audit_presenter.py`, dashboard Revisión/Operaciones, pruebas y guías.
5. **Migraciones.** Ninguna; sin cambios de contratos API/Broker ni datos existentes.
6. **Tests.** Ocho nuevos: snapshot histórico frente a decisión actual, paginación
   con revisiones concurrentes, simulación de autorización distinta de ejecución,
   publicación/reversión, legado sin snapshot, error con reintento/hilo, cierre con
   resultado tardío y navegación. Pruebas existentes de procesador y widgets ampliadas.
7. **Verificación.** Ocho pruebas en 6,170 s sin fallos; ruff/mypy pasan sobre
   145 archivos. Batería completa final registrada debajo. La prueba nativa sigue
   condicionada a disponibilidad de Tcl/Tk; no se acredita render por código.
8. **Riesgos/deuda.** Revisor detectó una etiqueta que confundía simulación de ejecución
   con autorización y una revisión desplazada fuera de su página al actualizar.
   Corregidas con vínculo a decisión original y recolocación de la página manteniendo
   revisión exacta. Revisión final sin hallazgos materiales pendientes.
9. **Checkpoint.** Acceso local a trazabilidad implementado y comprobado con datos
   temporales. Render, recorrido visual integral, inventario global y flujo real externo
   siguen pendientes; no se declara completo el objetivo ni la fase 14.
10. **Próximo paso.** Completar inventario de entregables/globales y saneamiento de
    errores antiguos; conservar separados los ensayos locales de la evidencia real.

Verificación completa final del duodécimo incremento: **399 pruebas en 143,502 s;
394 pasan y cinco omisiones explícitas Tcl/Tk**. Ruff/mypy pasan sobre 145 archivos;
`diff --check` pasa. Objetivo y checkpoint global abiertos.

## Undécimo incremento: trazabilidad de análisis y transiciones (8 de septiembre de 2026)

1. **Estado encontrado.** Las filas de trabajos y candidatos conservaban su estado,
   pero faltaban eventos estructurados de análisis, intención y conflictos. La
   publicación semántica solo enlazaba candidato/nota en su evento de terminación.
2. **Diseño.** Emitir eventos dentro de la transacción que cambia el estado, con IDs
   y estados mínimos. No repetir eventos en operaciones idempotentes ni copiar texto
   de documentos, prompts, resultados o errores remotos.
3. **Cambios.** Transiciones de trabajos desde creación a envío/reintento/recuperación
   y terminación; creación/intención/conflicto de propuestas; conflictos inducidos
   por otra publicación. Evento APPLIED con actor, revisión, lote/ejecución y sucesor.
   Matriz de campos, observabilidad y reconstrucción apoyada en código y pruebas.
4. **Archivos.** `semantic_repository/trabajos.py`, `semantic_repository/candidatos.py`,
   `test_semantic_audit.py`, prueba del procesador semántico de fase 6 y documentación.
5. **Migraciones.** Ninguna; reutiliza events y registros existentes. No reconstruye
   eventos antiguos ni reescribe snapshots. Sin cambios de contrato Broker/API/UI.
6. **Tests.** Siete nuevos: reintentos/recuperación sin duplicados, error local/remoto,
   rollback del evento de trabajo, creación/conflicto con revisión optimista,
   atribución de publicación automática, conflicto de otra propuesta y rollback de
   intención. Prueba existente ampliada con campos/citas, tres tareas/modelos reportados,
   fecha y conservación del snapshot después de aprobación humana.
7. **Verificación.** Los siete casos nuevos pasan en 5,574 s. La prueba inicial
   alternaba dos estados reales al intentar comprobar sondeos repetidos; se corrigió
   para repetir cada estado por separado. Ruff/mypy pasan sobre 142 archivos.
   Batería completa final registrada debajo.
8. **Riesgos/deuda.** Los eventos históricos no se inventan. Modelos declarados por
   un Broker simulado no acreditan inferencia real. Falta inspeccionar saneamiento
   integral de rutas de error antiguas y acceso a toda la auditoría desde la interfaz.
9. **Checkpoint.** Auditoría transaccional nueva verificada localmente, sin UI nueva,
   migraciones ni cambios en datos del usuario. El objetivo global sigue abierto.
10. **Próximo paso.** Completar el inventario de entregables/globales y contrastar la
    navegación de auditoría con la exigencia de comprender el flujo sin SQLite/logs.

Verificación completa final del undécimo incremento: **391 pruebas en 195,176 s;
386 pasan y cinco omisiones explícitas Tcl/Tk**. Ruff/mypy pasan sobre 142 archivos;
`diff --check` pasa. El objetivo global permanece abierto.

## Décimo incremento: evaluación por políticas desde una propuesta (8 de septiembre de 2026)

1. **Estado encontrado.** El assessment afirmaba ausencia de políticas de forma fija,
   aunque el motor de gobernanza ya las admitía. La revisión individual no transfería
   su selección a ese motor. Los snapshots existentes deben conservarse inmutables.
2. **Diseño.** Separar evaluación de propuesta y simulación de una política explícita.
   Conservar exactamente candidato/revisión y cualquier borrador al abrir políticas.
3. **Cambios.** Assessments nuevos indican evaluación de política pendiente; detalle
   API con contexto explicativo y selección exacta. Botón Evaluar con política y
   simulación filtrada; retirada explícita del filtro. Historial describe su propio
   ámbito y no habilita autorización si no coincide. Comparación con desplazamiento
   exterior, altura mínima y foco visible, conservando las acciones fuera del canvas.
4. **Archivos.** Assessment/servicio semántico, schema API, panel/presentador/vista de
   simulación, dashboard Revisión/Servicios, pruebas de propuestas/políticas y guías.
5. **Migraciones.** Ninguna. No se reescriben snapshots, trabajos ni políticas existentes.
6. **Tests.** Siete casos nuevos: política existente, histórico byte a byte por API,
   selección única/borrador, revisión obsoleta, respuesta perdida, historial ajeno y
   navegación. Prueba nativa ampliada a tres notebooks en 1080×680; prueba de foco
   reutilizada para la comparación. Tokens de prueba ficticios y notas temporales.
7. **Verificación.** Siete casos nuevos pasan en 6,882 s. Ruff/mypy pasan sobre
   142 archivos. Dos defectos de la prueba inicial corregidos: longitud del token
   ficticio y lectura de la envoltura `review` del contrato existente. Batería completa
   final registrada debajo.
8. **Riesgos/deuda.** Revisión independiente detectó ámbito histórico engañoso y riesgo
   de comparación recortada; ambos corregidos y revisión final sin hallazgos materiales.
   Render, flujo externo y auditoría global de campos/eventos/entregables siguen abiertos.
9. **Checkpoint.** Puente y guardas de selección verificados localmente. La evaluación
   de propuesta no autoriza publicaciones. No se usó ni guardó el token real recibido.
   Fase 14 y objetivo global permanecen abiertos por las verificaciones pendientes.
10. **Próximo paso.** Completar trazabilidad de campos, eventos y entregables contra
    código/pruebas, manteniendo separada la evidencia local de los ensayos reales.

Verificación completa final del décimo incremento: **384 pruebas en 194,926 s;
379 pasan y cinco omisiones explícitas Tcl/Tk**. Ruff/mypy pasan sobre 142 archivos;
`diff --check` pasa. No se declara cerrado el objetivo global.

## Noveno incremento: límites ante instrucciones dentro de fuentes

1. **Estado encontrado.** El caso obligatorio 18 solo tenía cobertura de consulta.
   Extracción marcaba datos no confiables sin prohibición expresa de obedecerlos,
   y las etiquetas del documento podían aparecer como delimitadores del prompt.
2. **Diseño.** Datos JSON reversibles con delimitadores protegidos; reglas explícitas
   de extracción/comparación/embeddings y pruebas sobre las barreras del servicio.
3. **Cambios.** Instrucciones de fuente no confieren roles, herramientas, permisos
   ni aprobación. Escape de etiquetas en documento, identificador, citas y contexto;
   conserva Unicode y spans. Se verifican contratos, bloqueos y gobernanza separados.
4. **Archivos.** `services/semantic_maintenance/prompts.py`,
   `tests/test_untrusted_source_boundaries.py`, prueba de prompt en fase 6,
   guía `Untrusted_Source_Boundaries.md` y matriz de aceptación.
5. **Migraciones.** Ninguna; no se reescriben trabajos durables ni cambia el contrato Broker.
6. **Tests.** Cinco casos: delimitadores/Unicode, extracción adversaria sin efectos
   parciales, comparación con órdenes no admitidas/manual_lock, confianza y revisión
   humana preservadas, embedding sin canal de comandos.
7. **Verificación.** Cinco pruebas en 3,762 s sin fallos. Ruff/mypy pasan sobre
   142 archivos. La primera batería detectó una aserción antigua que exigía etiquetas
   sin escape; se sustituyó por recuperación exacta del JSON y ausencia de delimitador
   inyectable. Los seis casos enfocados pasan en 3,960 s; batería final registrada debajo.
8. **Riesgos/deuda.** Los ensayos locales no acreditan resistencia de un modelo real.
   Se detectó otra carencia de aceptación: el assessment histórico presenta una
   ausencia fija de política; debe distinguirse de la evaluación real de gobernanza.
   Render, revisión independiente de políticas y flujo externo siguen pendientes.
9. **Checkpoint.** Barreras locales del caso 18 verificadas; objetivo global abierto.
   Solo fuentes/notas temporales, sin utilizar ni guardar el token real del Broker.
10. **Próximo paso.** Corregir la explicación de elegibilidad en propuestas sin alterar
    snapshots históricos; continuar la auditoría de campos, eventos y entregables.

Verificación completa final del noveno incremento: **377 pruebas en 176,952 s;
372 pasan y cinco omisiones explícitas Tcl/Tk**. Ruff/mypy pasan sobre 142 archivos
y `diff --check` pasa. El objetivo global sigue abierto.

## Octavo incremento: recuperación de navegación y auditoría de aceptación

1. **Estado encontrado.** Políticas, fuentes e historial adelantaban offsets antes
   de recibir datos; un error podía saltar resultados. El selector podía mostrar
   otra política mientras seguía cargado el borrador anterior. La repetición de
   «Simular siguientes» podía crear otra simulación tras perder una respuesta.
2. **Diseño.** Confirmar páginas junto con sus resultados, conservar borrador e
   identidad visibles ante fallo y fijar claves por solicitud de simulación.
   Navegación de foco mediante coordenadas reales del canvas.
3. **Cambios.** Las páginas fallidas se reintentan sin avanzar; política y borrador
   solo se limpian al recibir la nueva página. Historial conserva categoría/offset.
   Selección de política no cambia su etiqueta hasta leerla; la simulación siguiente
   mantiene la clave al reintentar y volver al inicio utiliza otra. Foco corregido y
   rueda del listado de fuentes separada del desplazamiento del formulario.
4. **Archivos.** `ui/automation_panel.py`, `ui/automation_form.py`,
   `tests/test_automation_ui.py`, guías y nueva matriz `Acceptance_Evidence.md`.
5. **Migraciones.** Ninguna; sin cambios en contratos públicos ni políticas guardadas.
6. **Tests.** Seis casos nuevos: páginas fallidas de políticas/fuentes/historial,
   selección fallida con borrador, respuesta perdida al simular páginas y foco con
   recorte superior/inferior. Se comprueba la identidad durable de las simulaciones.
7. **Verificación.** Pruebas UI: 18 en 8,777 s; 17 pasan y una omisión Tcl/Tk.
   Ruff/mypy pasan en 142 archivos; batería completa final registrada debajo.
8. **Riesgos/deuda.** Revisión independiente de Servicios/políticas aún pendiente:
   el intento del revisor terminó por cuota. Render sigue sin comprobarse por Tcl/Tk.
   La matriz detecta cobertura parcial del caso obligatorio 18: la prueba existente
   inyecta instrucciones en la consulta; falta probar la fuente durante extracción.
9. **Checkpoint.** Correcciones locales verificadas; fase 14 y aceptación global
   abiertas. La matriz distingue veinte escenarios controlados de la evidencia real
   que aún falta; no redefine el objetivo alrededor de las pruebas que ya pasan.
10. **Próximo paso.** Prueba adversaria de instrucciones dentro de una fuente,
    revisión de extracción/comparación y continuación de la auditoría de entregables.

Verificación completa del octavo incremento: **372 pruebas en 180,910 s; 367 pasan
y cinco omisiones explícitas Tcl/Tk**. Ruff/mypy pasan sobre 142 archivos y
`diff --check` pasa. No se usó ni guardó el token del Broker en este incremento.

## Séptimo incremento: revisión y recibos de reversión en API/UI (7 de septiembre de 2026)

1. **Estado encontrado.** El servicio de reversión tenía planes durables y recuperación;
   faltaban acceso por consumidor y revisión desde la aplicación.
2. **Diseño.** Cinco rutas con permiso `review` y planes privados del consumidor;
   extensión de Revisión con publicaciones, comparación completa, evidencia y recibos.
   Proyección compartida sin rutas ni filas internas; confirmación del plan/hash exacto.
3. **Cambios.** Listado paginado, vista previa, confirmación con motivo y auditoría.
   El escritorio consulta recibos de todos los actores pero solo confirma planes propios.
   I/O fuera de Tk, selección estable y bloqueo de decisiones tras lecturas inciertas.
   Reintento de preview conserva la clave; una respuesta perdida de confirmación se
   resuelve consultando el recibo. Los offsets solo avanzan tras lecturas correctas.
   Comparación con altura mínima y desplazamiento exterior, acciones fijas y foco visible.
4. **Archivos.** `api/reversions.py`, integración application/OpenAPI/response_schemas,
   `services/reversion_view.py`, `repositories/reversion_repository.py`,
   `ui/reversion_panel.py`, `ui/dashboard/revision.py`, dos archivos de pruebas y guías.
5. **Migraciones.** Ninguna adicional: utiliza la migración 021 y conserva el contrato
   del servicio, sus reservas y recuperación.
6. **Tests.** Siete casos API: permisos, contratos, privacidad, idempotencia, conflictos,
   pérdida de respuesta y HTTP real de loopback. Diez casos UI: cancelación, claves
   estables, lectura incierta, confirmación perdida, auditoría ajena, selección/arranque,
   paginación fallida, hilo de widgets, foco y flujo nativo con ventana reducida.
7. **Verificación.** Pruebas propias: 17 en 15,554 s; 16 pasan y una omisión Tcl/Tk.
   Ruff/mypy pasan sobre 142 archivos. Batería completa final registrada debajo.
8. **Riesgos/deuda.** Render y flujo nativo no acreditados: falta `init.tcl` utilizable.
   La revisión independiente de código finaliza sin correcciones pendientes después
   de resolver paginación, altura y desplazamiento de foco; no sustituye el render.
   La integración externa Broker/red conserva las limitaciones ya documentadas.
9. **Checkpoint.** API y lógica de revisión verificadas localmente; checkpoint visual
   y fase 14 abiertos. Solo se modificaron notas/bases temporales durante las pruebas.
10. **Próximo paso.** Completar revisión de los incrementos visuales anteriores y
    verificar el flujo nativo e integración real cuando el entorno lo permita;
    contrastar la evidencia acumulada con los criterios globales de aceptación.

Verificación completa del séptimo incremento: **366 pruebas en 169,196 s; 361 pasan
y cinco omisiones explícitas Tcl/Tk**. Ruff/mypy pasan en 142 archivos y
`diff --check` no informa errores. El checkpoint global permanece abierto.

## Sexto incremento: reversión conservadora de dominio (7 de septiembre de 2026)

1. **Estado encontrado.** Publicación y autoaprobación conservaban snapshots y sucesiones,
   pero no había una compensación confirmada y recuperable. Se reutilizan esas revisiones
   y el reemplazo atómico; la restauración no usa un backup de toda la base de datos.
2. **Diseño.** Plan inmutable, separado por actor, con hash revisado y motivo obligatorio.
   Solo la publicación más reciente con estado/evidencia exactos. Revalidación y reserva
   de notas en una transacción antes de escribir; recuperación previa a los workers.
3. **Cambios.** Vista previa durable, confirmación idempotente, publicación, recibo y
   conflictos. El claim anterior obtiene una nueva revisión/período y su estado revisable
   previo; el sucesor retirado pasa a HISTORICAL con vínculo al restablecido. Ningún
   histórico se edita o borra. No se alteran el APPLIED original ni sus cupos/recibos.
   Las reservas bloquean aplicaciones, extracciones y decisiones concurrentes y excluyen
   temporalmente las notas implicadas de CURRENT. La evidencia se comprueba por bytes,
   hashes y citas. Los claims no afectados recuperan sus posiciones, en un orden que
   evita colisiones transitorias entre citas iguales.
4. **Archivos.** `reversion_guards.py`, `reversion_repository.py`, servicio
   `maintenance_reversion.py`, guardas compartidas/consultas/extracción, runtime,
   migración 021, pruebas de reversión/migración y guía `Maintenance_Reversion.md`.
5. **Migración.** 021 aditiva: planes/decisiones/recibos y reservas por nota. Versiones
   existentes, propuestas, activaciones y datos del usuario permanecen intactos.
6. **Tests.** Restauración/historial, idempotencia/aislamiento, planes inmutables,
   confirmación exacta, `manual_lock`, cambios externos, decisiones posteriores,
   interrupciones, reservas, concurrencia, fallo SQLite, conflictos, claims no afectados,
   dependencias, snapshot dañado, procedencia restaurada y recuperación del runtime.
7. **Verificación.** Los 19 casos propios pasan en 40,689 s. Batería completa final:
   **349 pruebas en 132,871 s; 345 pasan y cuatro omisiones explícitas Tcl/Tk**.
   Ruff y mypy pasan sobre 139 archivos; `diff --check` pasa.
8. **Riesgos/deuda.** API/UI de reversión aún pendientes: este incremento implementa
   el servicio y la recuperación. No hay reversión en cascada ni restauración sobre
   cambios posteriores. NTFS/SQLite/editor externo conservan el límite de consistencia
   mediante hashes/reconciliación; no se afirma una transacción distribuida. Las pruebas
   visuales y externas mantienen las limitaciones documentadas en los incrementos previos.
9. **Checkpoint.** Reversión de dominio verificada localmente; fase 14 abierta. Solo se han
   aplicado reversiones sobre bases y notas temporales de pruebas; sin usar el Broker.
10. **Próximo paso.** Exponer vista previa, confirmación y recibos de reversión en API/UI
    mediante estos servicios, con revisión explícita y permisos; continuar las pruebas
    visuales, revisión independiente e integración externa pendientes.

## Quinto incremento: controles de políticas en Servicios (7 de septiembre de 2026)

1. **Estado encontrado.** Los servicios y la API permitían gobernar la automatización;
   Servicios mostraba procesos, pero faltaba configurar y revisar políticas desde la UI.
2. **Diseño.** Extensión local de Tkinter/ttk y de Servicios, conservando la dirección
   visual existente. Formulario, simulación antes/propuesto e historial separados;
   selección explícita, versiones esperadas y decisiones con confirmación/motivo.
   El control global usa un canal independiente para poder pausar durante una simulación.
3. **Cambios.** Crear/editar desactivada, seleccionar fuentes entre páginas, simular
   entre 1 y 100 propuestas del ámbito por página, revisar evidencia y exclusiones,
   autorizar la versión revisada, desautorizar y pausar/reanudar. Historial de versiones,
   decisiones, simulaciones, ejecuciones y control global. Lecturas/escrituras fuera
   del hilo Tk; los controles esperan a la recuperación inicial. Actualización del
   control visible cada cinco segundos sin sustituir borradores. Claves estables de
   creación/simulación conservan idempotencia tras respuestas perdidas.
4. **Archivos.** `ui/automation_panel.py`, `automation_form.py`, `automation_plan.py`,
   `automation_presenter.py`, integración `ui/dashboard/servicios.py`, servicio de
   gobernanza y selector del planificador, `tests/test_automation_ui.py` y documentación.
5. **Migraciones.** Ninguna nueva: utiliza las tablas 017–020. La selección del worker
   conserva su paginación circular de hasta 1000; la UI usa páginas acotadas sin vuelta
   automática al inicio y conserva su selección exacta en el plan inmutable.
6. **Tests.** Doce casos nuevos: validación de condiciones/ámbito, revisiones exactas
   y borrador, selección de fuentes entre páginas, pausa durante trabajo pendiente,
   cancelación, bloqueo durante arranque, recuperación del estado ocupado tras error,
   refresco del control sin pisar borrador, páginas/repetición idempotente, respuesta
   perdida tras crear, selección estable del historial y flujo de widgets nativos.
7. **Verificación.** Pruebas propias: 12 en 5,458 s, once pasan y una omisión Tcl/Tk.
   Batería completa final: **330 pruebas en 121,010 s; 326 pasan y cuatro omisiones
   explícitas Tcl/Tk**. Ruff y mypy pasan sobre 136 archivos; `diff --check` pasa.
8. **Riesgos/deuda.** El render y el flujo nativo no pudieron verificarse: Tcl/Tk falla
   al inicializar `init.tcl`. La revisión independiente de esta UI no se completó por
   límite de uso del revisor; no se considera sustituida por las comprobaciones locales.
   Planes limitados a 8 MiB y vistas de texto abreviadas a 200 000 caracteres, con aviso.
   Broker/red reales y reversión conservadora siguen pendientes.
9. **Checkpoint.** Lógica del incremento verificada localmente; checkpoint visual y
   fase 14 abiertos. Solo se autorizaron políticas en bases temporales de pruebas.
   Ninguna activación en datos del usuario; el último token del Broker no se utilizó
   ni se guardó durante este incremento.
10. **Próximo paso.** Reversión conservadora con vista previa y decisión explícita,
    preservando revisiones, procedencia y estado temporal; bloquear cambios posteriores,
    dependencias y `manual_lock`. Completar después las verificaciones visuales y externas.

## Cuarto incremento: controles y auditoría por API (6 de septiembre de 2026)

1. **Estado encontrado.** El planificador ya funcionaba, pero configurar, autorizar,
   pausar y consultar sus recibos requería acceso directo a servicios de dominio.
2. **Diseño.** Permiso independiente `governance` para administración del runtime;
   decisiones con actor derivado del consumidor y revisiones esperadas. Autorizar por
   API requiere una simulación revisada de la misma política/versión/activación/control.
3. **Cambios.** Quince rutas de configuración, simulación, activación, pausa, historiales,
   planificación y recibos; contratos de solicitud/respuesta en OpenAPI. Simulaciones
   solicitadas idempotentes con persistencia conjunta de solicitud y plan. Nuevos
   métodos de servicio reutilizables por la futura UI. La etiqueta de permiso en
   Servicios incluye Gobernanza. Ningún consumidor existente recibe ese permiso solo.
4. **Archivos.** Adaptador/contratos/respuestas `api/automation*.py`, auth/application/
   OpenAPI, servicio y repositorio de gobernanza, repositorio de políticas, runtime,
   migración 020, pruebas API/migraciones y guía `Automation_Governance.md`.
5. **Migración.** 020 aditiva: solicitudes idempotentes inmutables y vínculo de decisión
   a simulación revisada. No modifica activaciones, pausa, notas ni histórico existente.
6. **Tests.** Doce casos: permisos en las quince rutas, creación desactivada, actor no
   suplantable, repetición/concurrencia de simulaciones, atomicidad ante fallo SQLite,
   simulación ajena/obsoleta, edición revocatoria, pausa versionada, historial/paginación,
   schemas OpenAPI, errores saneados y flujo API → planificador → publicación.
7. **Verificación.** Las 12 pruebas pasan en 9,456 s. Una usa HTTP real de loopback:
   401 sin credencial, 403 con permiso de revisión y pausa válida con gobernanza;
   la ejecución encolada queda SKIPPED/AUTOMATION_PAUSED y la nota permanece intacta.
   Batería completa: **318 pruebas en 113,597 s; 315 pasan y tres omisiones explícitas
   Tcl/Tk**. Ruff y mypy pasan sobre 132 archivos.
8. **Riesgos/deuda.** `governance` es un permiso administrativo global del runtime,
   no aislamiento entre administradores; documentado explícitamente. Los PATCH con
   revisiones detectan una repetición mediante 409; no generan decisiones adicionales.
   Los controles visuales, reversión y verificaciones Broker/red/Tk siguen pendientes.
9. **Checkpoint.** API de gobernanza verificada localmente; fase 14 aún abierta.
   Solo se habilitaron políticas en bases temporales de pruebas. El token real del Broker
   no se utilizó ni se persistió durante este incremento.
10. **Próximo paso.** Controles visuales de configuración, simulación, autorización,
    pausa y auditoría usando estos mismos servicios; después reversión conservadora.

## Tercer incremento: planificador periódico (6 de septiembre de 2026)

1. **Estado encontrado.** Existían políticas, simulaciones y ejecución recuperable,
   pero faltaba descubrir propuestas y ejecutar políticas en segundo plano.
2. **Diseño.** Worker local posterior a recuperación, independiente del Broker.
   Evalúa políticas autorizadas con control global reanudado; arrendamiento de 20 minutos,
   comprobaciones cada 60 segundos y espera tras fallos de hasta una hora. Cada política
   conserva cursor, última evaluación, incidencias y vínculos a simulación/ejecución.
3. **Cambios realizados.** Descubrimiento por recibos de fuentes del ámbito aprobado,
   páginas de hasta 1000 propuestas, validación completa y guardado conjunto de simulación,
   ejecución y cursor. Huellas persistidas evitan repetir el mismo plan incluso al alternar
   páginas o reiniciar. La huella incluye versión/activación, control global, día UTC,
   uso de cupo y contenido del plan. Un plan superior a 8 MiB se divide; si una sola
   propuesta excede ese tamaño, queda pendiente de revisión, se registra su identificador
   y revisión y el cursor avanza para permitir procesar las siguientes.
4. **Archivos.** `automation_schedule_repository.py`, `automation_scheduler.py`,
   `automation_worker.py`, runtime, repositorios de simulaciones/ejecuciones, simulación,
   dominio de automatización, estado de Servicios y pruebas del planificador/estado.
5. **Migración.** 019 aditiva: estado de planificación y asociación de huellas a planes
   durables. No cambia las autorizaciones ni toca notas, reservas o histórico existente.
6. **Tests.** Quince casos nuevos: pausa/desactivación por defecto, publicación con
   atribución sin Broker, deduplicación tras reinicio y entre páginas, atomicidad ante
   fallo SQLite, exclusión de arrendamientos caducados, pausa/edición concurrentes,
   dos planificadores, ejecución pendiente de recuperación, espera tras errores sin
   bloquear otras políticas, parada/estado real, más de 1000 propuestas y tamaños grandes.
7. **Verificación.** Las 15 pruebas pasan en 14,858 s. Batería completa: **306 pruebas
   en 103,711 s; 303 pasan y tres se omiten explícitamente por Tcl/Tk**. Ruff y mypy
   pasan sobre 127 archivos; comprobación de espacios sin errores.
8. **Riesgos/deuda.** Los controles de políticas en API/UI y la reversión conservadora
   siguen pendientes. Una evaluación sin cambios reutiliza su recibo; un fallo de ejecución
   no provoca repeticiones ilimitadas del mismo plan. La revisión/reformulación humana
   permite tratar propuestas que requieran otro intento. Propuestas individuales de más
   de 8 MiB necesitan revisión o división; no se publican automáticamente. Las pruebas
   de Broker/red y render Tk siguen pendientes por las limitaciones documentadas.
9. **Checkpoint.** Planificador verificado localmente; fase 14 aún abierta. Todas las
   pruebas que autorizan políticas usan bases temporales. El arranque conserva el control
   pausado y las políticas desactivadas hasta decisiones humanas explícitas. La pantalla
   Servicios muestra worker, pausa, evaluaciones, incidencias y ejecuciones pendientes.
10. **Próximo paso.** Controles de configuración/simulación/autorización y pausa en API/UI,
    con permisos separados y revisión de versiones; después reversión conservadora y
    verificación integral y visual pendiente.

La pausa impide **nuevas intenciones**. Una intención ya reservada puede terminar o
recuperarse estando el control pausado. El worker atiende primero los recibos pendientes;
no vuelve a evaluar una política con ejecución READY, RUNNING o RECOVERY_REQUIRED.
El arrendamiento solo permite guardar al propietario vigente y se comprueba junto a
las revisiones de autorización dentro de la transacción. La elegibilidad y los cupos
se comprueban nuevamente antes de cada intención de publicación.

## Diseño inicial

1. **Estado encontrado.** Hay propuestas versionadas, guardas de aplicación compartidas,
   evidencia/hash, lotes humanos recuperables y workers. La evaluación automática está
   desactivada y devuelve NO_APPROVED_POLICY. No existen políticas persistidas.
2. **Diseño.** Políticas con fuentes explícitas, tipos/roles permitidos, umbrales,
   relaciones, tipos de claim y límites por tarea/ejecución/día. Crear o editar una
   política la deja desactivada. Activar requiere revisión exacta, actor y decisión
   explícita. Control global separado, pausado por defecto, también versionado.
3. **Cambios previstos.** Configuración validada, repositorio inmutable de versiones,
   decisiones y control global; simulación sin publicaciones; ejecución durable que
   revalida autorización y cupos dentro de la transacción de intención.
4. **Archivos previstos.** Dominio/repository de políticas, servicio de simulación y
   ejecución, guardas semánticas, worker, API/controles de UI y pruebas de gobernanza.
5. **Migraciones previstas.** Aditivas para políticas/versiones/decisiones, control
   global y ejecuciones. No alterar ni borrar notas o histórico al migrar.
6. **Tests previstos.** Versionado, activación obsoleta, ausencia de ámbito, contradicción,
   manual_lock, hashes cambiados, cupos, pausa concurrente, revocación de versión,
   recuperación, resultados parciales y reversión conservadora cuando sea segura.
7. **Verificación de entrada.** 267 pruebas: 264 pasan, tres omisiones Tcl/Tk; ruff/mypy
   pasan. Render, revisión independiente del último incremento y redes externas son
   limitaciones documentadas, no fallos conocidos del núcleo.
8. **Riesgos/deuda.** La fuente y confianza del modelo no prueban hechos. Una política
   nunca resolverá contradicciones automáticamente ni podrá ignorar bloqueos manuales.
   No confundir una simulación elegible con una autorización para publicar.
9. **Checkpoint.** Fase iniciada; aún no implementada la ejecución por políticas.
10. **Próximo paso.** Persistir configuración/versiones y decisiones; validar simulación
    con fuentes monitorizadas y propuestas reales del flujo existente.

## Invariantes de ejecución acordados para implementar

- La evidencia exacta, procedencia, estados CURRENT, fuente habilitada y configuración
  vigente deberán volver a comprobarse antes de reservar una aplicación automática.
- La autorización debe vincular política/revisión, control global/revisión, candidato/
  revisión y ejecución. Cambiar o desactivar política revoca decisiones no iniciadas.
- El interruptor global impide iniciar nuevas escrituras; una intención ya reservada
  se recupera para conservar consistencia, sin añadir tareas al plan autorizado.
- Reservar cupos y publicación en la misma transacción; una caída no puede liberar un
  cupo de una escritura cuyo resultado aún no se conoce.
- La reversión conservará el histórico y exigirá estado/hash exactos y ausencia de
  dependencias posteriores. Si no puede demostrarse, devolver conflicto para revisión
  humana en lugar de restaurar a ciegas una nota antigua.

## Primer incremento: configuración y simulación

1. **Estado encontrado.** La autoaprobación era una etiqueta fija sin políticas. Se
   reutilizan propuestas/evidencia y la preview de aplicación individual ya verificada.
2. **Diseño aplicado.** Configuración inmutable con fuentes explícitas, filtros de
   tipo/rol, relación, tipo de claim, umbrales y límites. Revisión de contenido separada
   de revisión de activación para detectar decisiones concurrentes, además del control
   global versionado y pausado por defecto.
3. **Cambios realizados.** Crear/editar/autorizar/desautorizar políticas como servicios
   de dominio; edición revoca autorización. Historial de versiones y decisiones;
   simulaciones durables con antes/después/evidencia y motivos de exclusión. Se revisan
   ambas afirmaciones CURRENT, procedencia monitorizada real, revisión/configuración de
   fuente, bloqueos, hashes, dependencias y límite de tareas por simulación.
4. **Archivos.** `domain/automation.py`, `repositories/automation_repository.py`,
   `services/automation_simulation.py`, migración 017, runtime, estado de servicios,
   pruebas de gobernanza y comprobación de migraciones.
5. **Migración.** 017 aditiva: políticas, versiones, decisiones, control global/historial
   y simulaciones. Triggers impiden modificar/borrar versiones, decisiones y simulaciones.
   Probada en bases temporales nuevas y en migración desde fase 1, conservando captura.
6. **Tests.** Diez casos de gobernanza: ámbito obligatorio, límites/tipos inválidos,
   creación idempotente desactivada, revisión/activación obsoleta, edición revocatoria,
   historial inmutable, control global explícito, simulación sin publicaciones incluso
   con política autorizada, manual_lock, evidencia cambiada, contradicciones con alta
   confianza, revisión/trust de fuente cambiado, política editada durante simulación
   y límite de ejecución sobre propuestas independientes.
7. **Verificación.** Diez pruebas en 7,176 s sin fallos. Ruff y mypy pasan (121 archivos);
   diff sin errores de espacios. Batería completa final registrada debajo.
8. **Riesgos/deuda.** La ejecución por políticas, cupos diarios transaccionales,
   recuperación de ejecuciones, reversión y controles API/UI aún no están implementados.
   `daily_quota_evaluated=false`, `limits_reserved=false` y `publication_authorized=false`
   aparecen explícitos en simulaciones. Una simulación elegible no autoriza aplicación.
   La preview está acotada a 1000 propuestas y 8 MiB durante construcción/persistencia.
9. **Checkpoint.** Base de configuración y simulación verificada localmente; NO es el
   checkpoint completo de gobernanza. No se ha habilitado ninguna política en datos
   del usuario. La UI muestra recuentos/estado e indica que el motor sigue en desarrollo.
10. **Próximo paso.** Registro durable de ejecuciones/cupos y autorización revalidada
    dentro de la transacción que reserva publicación; después worker, API/UI y pruebas
    de revocación/pausa concurrentes y recuperación de resultados parciales.

Verificación completa del primer incremento: **277 pruebas en 80,911 s; 274 pasan y
tres omisiones explícitas Tcl/Tk**. Ruff y mypy pasan en 121 archivos. No se declara
completa la fase 14: falta el ejecutor con sus guardas transaccionales y controles.

## Segundo incremento: ejecución y cupos transaccionales

1. **Estado encontrado.** La simulación no reservaba cupos ni tenía un ejecutor. Se
   reutilizan la publicación recuperable y sus intenciones; la autorización automática
   se añade antes de crear la revisión y el estado APPLYING.
2. **Diseño.** Cada ejecución fija simulación, política/revisión, revisión de activación,
   revisión del control global y propuestas/revisiones. La misma transacción verifica
   autorización y elegibilidad, reserva cupo e intención. La pausa impide nuevas
   reservas; intenciones ya autorizadas conservan su recuperación.
3. **Cambios.** Ejecutor de dominio con recibos por tarea, recuperación y atribución
   `automation_run_id`; validación SQL compartida con simulación, procedencia dentro
   de esa transacción, contador diario UTC por política y límite por ejecución. Editar,
   desactivar, pausar o pausar/reanudar revoca planes no iniciados. Las reservas no se
   borran ni se reinician al editar la política. La simulación consulta el cupo diario
   existente pero no lo consume; los límites se vuelven a verificar al publicar.
4. **Archivos.** `automation_guards.py`, `automation_run_repository.py`,
   `automation_execution.py`, simulación/procedencia, servicio/repositorio/modelo
   semántico, runtime, estado de servicios y pruebas de ejecución.
5. **Migración.** 018 aditiva: ejecuciones, elementos, reservas inmutables, índices
   para cupo diario y vínculo de candidato a ejecución automática. Sin borrar histórico.
6. **Tests.** Catorce nuevos casos: autorización/pausa, aplicación única con histórico,
   revocación de política/fuente, manual_lock, rollback conjunto de cupo/intención ante
   fallo SQLite, competencia de dos ejecuciones por un cupo diario, caídas antes/después
   de intención y publicación, recibo perdido, resultados parciales, reanudación que
   no valida planes antiguos y edición que no reinicia el consumo diario.
7. **Verificación.** 24 pruebas de gobernanza/ejecución en 19,814 s sin fallos. Ruff y
   mypy pasan (124 archivos). Batería completa final registrada debajo.
8. **Riesgos/deuda.** El planificador periódico, controles API/UI y reversión conservadora
   siguen pendientes. El ejecutor existe como servicio de dominio; no hay worker que
   descubra y aplique automáticamente políticas en segundo plano todavía. Las reservas
   fallidas tras una intención siguen consumiendo cupo: evita reutilizar presupuesto de
   una escritura ambigua. El día de cuota es UTC, explícito en simulación y pantalla.
9. **Checkpoint.** Núcleo de ejecución/recuperación verificado localmente; no se declara
   completa la fase 14. Ninguna política activada en datos del usuario. La pantalla
   indica que la ejecución programada y los controles de políticas siguen en desarrollo.
10. **Próximo paso.** Planificador idempotente sobre políticas autorizadas, controles
    de simulación/activación/pausa y consulta de recibos en API/UI; reversión segura y
    pruebas integrales de automatización, incluidas cuotas y revocación en el worker.

Verificación completa del segundo incremento: **291 pruebas en 88,706 s; 288 pasan y
tres omisiones explícitas Tcl/Tk**. Ruff/mypy sin incidencias en 124 archivos. El
checkpoint completo de gobernanza permanece abierto por los elementos indicados arriba.
