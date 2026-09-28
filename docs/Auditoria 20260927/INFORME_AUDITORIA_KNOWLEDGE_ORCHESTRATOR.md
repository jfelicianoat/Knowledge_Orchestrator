# Knowledge Orchestrator: auditoría técnica, funcional y de usabilidad

**Fecha:** 27 de septiembre de 2026. **Versión declarada:** 0.3.3. **Commit examinado:** `846f3c689f5ae5bd1fbbb03386ee6d04f1a7b2bf`.

**Dictamen:** el proyecto dispone de una infraestructura considerable de persistencia, trazabilidad, protección de notas y gobernanza. Sin embargo, el ciclo completo de conocimiento todavía no ofrece las garantías que sugieren algunas opciones de la interfaz. Hay defectos reproducibles en aprobación, cancelación, recuperación, análisis semántico y tratamiento de documentos extensos. Recomiendo estabilizar ese ciclo antes de ampliar automatizaciones o añadir más pantallas.

## 1. Alcance y calidad de la evidencia

Se contrastaron README, PRODUCT, arquitectura, contratos, especificación del agente, estado vigente, plan de ciclo de vida, documentos de fases, aceptación, pruebas de usuario y contrato del puente. Se siguieron las rutas principales de ingesta, planificación, Broker, publicación, extracción, comparación, consultas, reconciliación, revisión, automatización, API y presentación.

La revisión de usabilidad se apoya en los textos y acciones reales implementados, en el flujo de servicios que ejecutan los controles y en la batería de widgets del proyecto. **No se realizó una nueva inspección visual manual ni una auditoría de accesibilidad con lector de pantalla.** Tampoco se ejecutaron inferencias contra el Broker del usuario, ni publicaciones dentro de su Obsidian real. Los testimonios de pruebas reales de septiembre son evidencia histórica del repositorio y se identifican como tales.

Todas las sondas nuevas usan bases y documentos temporales. No se modificó el código de producción, la configuración del usuario ni su bóveda. El repositorio no admitió la creación de la carpeta de informe; los entregables se guardaron en el directorio de resultados de esta conversación.

| Comprobación ejecutada ahora | Resultado |
|---|---|
| Batería Python mediante el inicializador de escritorio del proyecto | **490 pruebas, 318,021 segundos, OK**, sin omisiones notificadas |
| Puente de Obsidian, pruebas Node | **14 pruebas correctas**, sin omisiones |
| Ruff sobre código y pruebas | Correcto |
| mypy sobre código fuente | Correcto, **151 archivos** |
| Sondas adicionales de auditoría | **11 escenarios ejecutados**, resultados conservados en `probe-results.json` |

Que estas comprobaciones pasen acredita sus escenarios, no la ausencia de los defectos que se presentan a continuación. Los fallos nuevos se han encontrado precisamente en recorridos no cubiertos por esas aserciones.

**Clasificación:** P1 = corregir antes de considerar fiable el uso habitual o ampliar la automatización; P2 = mejora necesaria para completar el producto y evitar incidencias. «Reproducido» significa observado en una sonda aislada; «código» significa confirmado siguiendo la implementación; «riesgo» identifica un efecto que requiere una prueba adicional de entorno o escala. No se presenta un riesgo como una pérdida de datos ya ocurrida.

## 2. Intencionalidad frente a implementación

La intención central es convertir fuentes en conocimiento conservado, consultable, actualizable y trazable, mediante una aplicación de escritorio que permita resolver el trabajo sin consola. La implementación ha avanzado especialmente en control de cambios, pero la generación y recuperación de conocimiento útil quedan por detrás.

| Intención documentada | Implementación encontrada | Evaluación |
|---|---|---|
| Ingesta durable y conservación del original | Contrato, staging, hash, SQLite y recuperación; pruebas extensas | Base sólida; la entrada manual exige formato contractual |
| Procesar documentos extensos | División local, resultados parciales y una síntesis final | Parcial: la síntesis vuelve a superar el contexto |
| Revisión humana antes de publicar cuando se exige | La opción se envía al Broker; publicación local automática | Incumplimiento de la promesa de la interfaz |
| Cancelar un documento | Cancelación de una tarea concreta | Incompleto para documentos con varios fragmentos |
| Recuperarse de reinicios e incidencias | Intenciones persistidas y múltiples recuperadores | Una nota ausente puede interrumpir el arranque completo |
| Extraer afirmaciones verificables | Citas exactas dentro de la nota generada | Verifica la nota, no el respaldo en la fuente original |
| Mantenimiento semántico | Comparación, propuestas, revisiones, conflictos, sucesores y reversión | Núcleo significativo; extracción real y recuperación de errores limitan su utilidad |
| Convivir con cambios hechos en Obsidian | Detecta diferencias de hash y bloquea operaciones inseguras | Falta completar el recorrido para incorporar cambios humanos |
| Gestión de temas desde la aplicación | Servicios de dominio disponibles; pantalla de listado | Gestión funcional incompleta en la UI |
| Biblioteca y consultas | Biblioteca documental, FTS, API autenticada, consultas por selección de citas | Implementado; límites de descubrimiento, escala y puesta en marcha |
| Embeddings y recuperación semántica | Almacenamiento/búsqueda vectorial; generador de vector por chat sin circuito automático completo | No equivale a un sistema operativo de embeddings nativos |
| Gobernanza y cambios reversibles | Políticas, simulaciones, cuotas, permisos, snapshots y puente | Fortalezas locales; pendiente acreditar el ciclo real completo |
| Aplicación Windows instalable | Ejecutable y scripts; valores predeterminados ligados al equipo del autor | Portabilidad y primera ejecución insuficientes |

## 3. Hallazgos prioritarios

### H01 · P1 · La revisión humana obligatoria no detiene la publicación inicial

**Evidencia:** reproducido. Con `human_review_required=True`, la petición contiene la bandera correcta, pero al completar el resultado la nota termina en `PUBLISHED` y aparece físicamente en la bóveda sin ninguna decisión humana. La casilla dice literalmente «Exigir revisión humana antes de publicar».

**Causa:** `PublicationService.publish_ready()` publica los workflows terminados y `publish()` no consulta esa política. Transmitirla como metadata de riesgo al Broker no implementa una aprobación en el Orchestrator. Esto es distinto de las propuestas semánticas, que sí tienen controles de aprobación.

**Cambio necesario:** añadir un estado durable de borrador/pendiente de revisión de la nota inicial, vista previa, decisión explícita y auditoría. Evaluar la política antes de crear el archivo de publicación. La aceptación debe quedar vinculada a la versión concreta del resultado.

**Aceptación:** con la casilla marcada, completar el Broker y reiniciar no crea la nota publicada; solo una aprobación válida la publica. Rechazar conserva fuente y resultado para consulta o reprocesado.

Referencias: [src/knowledge_orchestrator/ui/dashboard/configuracion.py:270](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/ui/dashboard/configuracion.py:270>); [src/knowledge_orchestrator/services/publication.py:90](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/services/publication.py:90>); [src/knowledge_orchestrator/services/prompting.py:174](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/services/prompting.py:174>).

### H02 · P1 · Cancelar un documento no cancela sus demás tareas

**Evidencia:** reproducido con 11 fragmentos. Tras solicitar y confirmar la cancelación del primero, quedaron **10 tareas despachables**, el workflow en `ERROR` y la captura en `FAILED`.

**Causa:** la UI opera sobre el `task_id` seleccionado; `request_cancel()` solo modifica esa tarea. La selección de tareas despachables no filtra workflows terminales. Además, una cancelación termina por la misma ruta que un fallo.

**Impacto:** el usuario cree haber detenido el documento, pero el sistema puede seguir enviando fragmentos, ocupando modelos y consumiendo recursos. La pantalla puede presentar una cancelación como incidencia.

**Cambio necesario:** cancelar a nivel de workflow; detener tareas locales pendientes y solicitar cancelación de todas las remotas activas. Bloquear nuevos despachos y síntesis. Conservar `CANCELLED` como estado distinto de `ERROR`, y definir qué ocurre si la finalización gana la carrera a la cancelación.

**Aceptación:** cancelar un documento con fragmentos en estados mixtos no genera nuevos POST ni síntesis; el resultado sobrevive a reinicio y cancelación repetida.

Referencias: [src/knowledge_orchestrator/ui/dashboard/trabajo_acciones.py:129](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/ui/dashboard/trabajo_acciones.py:129>); [src/knowledge_orchestrator/repositories/workflow_repository/control.py:17](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/repositories/workflow_repository/control.py:17>); [src/knowledge_orchestrator/repositories/workflow_repository/consulta.py:35](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/repositories/workflow_repository/consulta.py:35>); [src/knowledge_orchestrator/repositories/workflow_repository/base.py:34](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/repositories/workflow_repository/base.py:34>).

### H03 · P1 · Una sola nota movida puede abortar la recuperación inicial

**Evidencia:** reproducido publicando una nota de ensayo, cambiando su nombre y ejecutando `recover_once()`. Se propaga `SemanticContractError` y la recuperación se interrumpe.

**Causa:** aunque la reconciliación detecta la ausencia, el arranque programa extracción para todas las notas `PUBLISHED`; `schedule_extraction()` intenta leer cada archivo antes de comprobar si ya existe un trabajo. No hay aislamiento del error por nota en ese bucle. Los workers se arrancan después.

**Cambio necesario:** aislar incidencias por documento; no reprogramar notas ausentes o en conflicto; consultar primero la necesidad del trabajo; continuar arrancando en modo degradado. Ofrecer localizar la nota movida, reindexar una versión aceptada o retirar el registro sin borrar evidencia.

**Aceptación:** con una nota desaparecida y otra sana, el escritorio y los workers quedan operativos; solo la primera exige atención. Repetir con archivo ilegible y codificación inválida.

Referencias: [src/knowledge_orchestrator/runtime.py:110](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/runtime.py:110>); [src/knowledge_orchestrator/runtime.py:127](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/runtime.py:127>); [src/knowledge_orchestrator/services/semantic_maintenance/__init__.py:76](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/services/semantic_maintenance/__init__.py:76>).

### H04 · P1 · Algunos JSON inválidos producen un bucle de error sin cerrar el análisis

**Evidencia:** reproducido con `volatility: []` dentro de una respuesta JSON de extracción. Dos consultas sucesivas producen `TypeError`; el trabajo permanece en `PROCESSING`.

**Causa:** la validación usa pertenencia a conjuntos antes de comprobar el tipo de ciertos campos. Una lista no es hashable. El procesador semántico solo captura determinados errores, por lo que este error escapa al bucle general. El mismo trabajo vuelve a ser leído en el siguiente ciclo y puede impedir atender los siguientes análisis y las consultas situadas después en ese ciclo.

**Cambio necesario:** validar tipos y estructura completos antes de operar; transformar todos los errores de contrato esperables en fallos tipados del trabajo; aislar cada elemento de la cola. Añadir pruebas de tipos arbitrarios en `volatility`, `relation`, `impact`, fechas y entidades.

**Aceptación:** toda respuesta inválida termina como incidencia recuperable del trabajo; otro trabajo válido del mismo lote continúa. Ningún contenido inválido crea claims parciales sin un contrato explícito que lo permita.

Referencias: [src/knowledge_orchestrator/services/semantic_maintenance/analisis.py:139](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/services/semantic_maintenance/analisis.py:139>); [src/knowledge_orchestrator/services/semantic_broker.py:73](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/services/semantic_broker.py:73>).

### H05 · P1 · Cambiar el modelo no permite recuperar un análisis semántico fallido

**Evidencia:** reproducido. Después de un error, se cambia `analysis_model` y se vuelve a ejecutar `schedule_extraction()`: mismo trabajo, misma petición, estado `ERROR`, cero trabajos despachables.

**Causa:** la identidad local es fija por nota y `create_job()` usa `ON CONFLICT(job_id) DO NOTHING`. La firma del contenido en la clave del Broker no resuelve el conflicto previo en SQLite. `recover_jobs()` recupera `SUBMITTING`, pero no ofrece una operación de reintento explícito de `ERROR`. La pantalla de análisis muestra código e intentos, sin una acción de recuperación equivalente a la de documentos.

**Cambio necesario:** modelar intentos/versiones del análisis con identidad propia, hash del documento, contrato, política y modelo. Ofrecer «Reintentar análisis» y «Reanalizar con la configuración actual»; conservar el historial anterior. Proteger frente a duplicados si el trabajo anterior sigue en curso.

**Aceptación:** un error seguido de cambio de modelo crea un intento nuevo y despachable; el intento anterior sigue consultable y los claims no se duplican.

Referencias: [src/knowledge_orchestrator/repositories/semantic_repository/trabajos.py:40](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/repositories/semantic_repository/trabajos.py:40>); [src/knowledge_orchestrator/repositories/semantic_repository/trabajos.py:161](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/repositories/semantic_repository/trabajos.py:161>); [src/knowledge_orchestrator/ui/dashboard/operaciones.py:184](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/ui/dashboard/operaciones.py:184>).

### H06 · P1 · La síntesis de documentos extensos no respeta el contexto

**Evidencia:** reproducido. Con ventana configurada de **4.000**, el plan crea 47 fragmentos y después una síntesis de **30.671 tokens estimados de entrada + 8.000 de salida**. Son estimaciones del propio programa, no medidas de un tokenizador real.

**Causa:** la planificación limita la salida de los fragmentos, pero `advance_workflow()` vuelve a leer el perfil original y concatena todos los resultados en una única síntesis, sin un control de contexto equivalente. La extracción semántica también envía el documento completo sin división. La ventana principal es una configuración fija, aunque el catálogo contiene información de modelos. No se encontró una ruta operativa de replanificación al recibir `CONTEXT_LIMIT_EXCEEDED`, pese a la promesa documental.

**Cambio necesario:** presupuesto de entrada/salida por paso y modelo; reducción jerárquica durable cuando los resúmenes no caben; segmentación de extracción; replanificación explícita ante límite de contexto. Considerar también la envoltura final del prompt y los cambios de modelo en reintentos.

**Aceptación:** cada petición satisface entrada estimada conservadora + salida + margen ≤ ventana admitida. Validar documentos largos, muchos resúmenes, modelos pequeños y reanudación en un nivel intermedio de síntesis.

Referencias: [src/knowledge_orchestrator/services/workflow_planner.py:66](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/services/workflow_planner.py:66>); [src/knowledge_orchestrator/services/workflow_planner.py:189](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/services/workflow_planner.py:189>); [src/knowledge_orchestrator/config.py:150](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/config.py:150>); [Agent_Knowledge_Orchestrator.md:511](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/Agent_Knowledge_Orchestrator.md:511>).

### H07 · P1 · La evidencia exacta puede respaldar una invención del resumen

**Evidencia:** reproducido con una salida de Broker simulada que añade «La Luna está hecha de queso». Esa frase no figura en la fuente original de ensayo, pero al extraerla de la nota se almacena como claim `CURRENT`.

**Interpretación precisa:** `CURRENT` significa vigencia local y el producto advierte que no equivale a verificación factual. No se está afirmando que ese estado prometa verdad absoluta. El problema es anterior: la cadena de evidencia exacta empieza en un resumen escrito por IA y no demuestra que la fuente original respalde la afirmación. La UI muestra fuentes originales junto a citas de la nota, lo que exige mucha claridad sobre esta diferencia.

**Cambio necesario:** extraer evidencia del original inmutable; asignar identificadores de segmentos y conservar hash/offsets de esa fuente. Vincular las formulaciones del resumen a esos segmentos. Distinguir evidencia primaria, resumen generado y validación humana. No resolver el fallo de extracción admitiendo paráfrasis como si fueran citas exactas.

La última evidencia real del repositorio reconoce que la extracción seguía sin producir afirmaciones utilizables. Conviene medir calidad sobre un corpus real antes de ampliar políticas automáticas. Si una respuesta mezcla citas válidas e inválidas, puede diseñarse un contrato nuevo con errores por segmento o reintentos acotados; la actual exigencia de atomicidad no debe relajarse silenciosamente.

**Aceptación:** una afirmación inventada en el resumen nunca queda respaldada por la fuente; una afirmación real puede abrirse en su contexto original. Medir precisión de citas, cobertura, falsos cambios, latencia y coste.

Referencias: [src/knowledge_orchestrator/services/semantic_maintenance/__init__.py:80](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/services/semantic_maintenance/__init__.py:80>); [src/knowledge_orchestrator/services/semantic_maintenance/analisis.py:96](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/services/semantic_maintenance/analisis.py:96>); [src/knowledge_orchestrator/services/knowledge_access.py:71](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/services/knowledge_access.py:71>); [docs/CURRENT_STATE.md:58](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/docs/CURRENT_STATE.md:58>).

### H08 · P1 · El «presupuesto por documento» se multiplica por el número de tareas

**Evidencia:** código y sonda de documento extenso. Cada uno de los 47 fragmentos recibe `max_cost_usd=0.05`; la síntesis recibe otros 0,05. El límite local no es una bolsa compartida de 0,05 USD por documento.

**Impacto:** si esos pasos se ejecutan en un proveedor con coste y consumen todo su límite, el conjunto permitiría hasta **2,40 USD** antes de considerar otros intentos; es un techo teórico de esas peticiones, no un gasto observado. Una cuota global del Broker podría imponer un límite adicional, pero no implementa el presupuesto por documento anunciado aquí.

**Cambio necesario:** reservar y liquidar presupuesto a nivel de workflow, descontando invocaciones, síntesis y reintentos. Mostrar importe reservado/consumido/restante. Si el producto solo desea un límite por tarea, renombrar el control y mostrar la estimación total antes del envío.

**Aceptación:** un documento dividido nunca puede reservar más que su presupuesto total; cubrir reintentos y reinicios. No continuar por una ruta alternativa cuando se agota el presupuesto.

Referencias: [src/knowledge_orchestrator/ui/dashboard/configuracion.py:258](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/ui/dashboard/configuracion.py:258>); [src/knowledge_orchestrator/services/prompting.py:121](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/services/prompting.py:121>); [src/knowledge_orchestrator/services/workflow_planner.py:114](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/services/workflow_planner.py:114>).

### H09 · P1 · La primera ejecución depende de una ruta privada antes de abrir Ajustes

**Evidencia:** código. El valor predeterminado es `Y:/Mi unidad/Vaults/Conocimiento_Youtube`, con estado e inbox dentro de esa ubicación. `main()` construye el runtime y crea directorios antes de abrir la interfaz. El Broker predeterminado también es una IP concreta de la red del autor.

**Impacto condicionado al entorno:** una instalación sin esa unidad puede fallar antes de ofrecer un selector de carpetas. Los tests que usan `home` explícito recorren una alternativa diferente y no demuestran una primera ejecución limpia con los valores reales predeterminados.

**Cambio necesario:** estado local por usuario en una ubicación disponible, asistente de primera ejecución y conexión al Broker sin asumir la red del autor. Separar la base operativa del vault. Si se admite una ubicación sincronizada o de red, validarla y documentar el alcance; SQLite WAL tiene restricciones explícitas de acceso entre máquinas en sistemas de red, sin que ello demuestre por sí mismo un fallo en esta unidad concreta. [Documentación de SQLite WAL](https://sqlite.org/wal.html).

**Aceptación:** una cuenta Windows limpia, sin Y: y sin Broker, abre la app y permite configurar rutas. Una ubicación indisponible produce un modo recuperable, no un cierre previo al escritorio.

Referencias: [src/knowledge_orchestrator/config.py:15](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/config.py:15>); [src/knowledge_orchestrator/app.py:30](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/app.py:30>); [src/knowledge_orchestrator/runtime.py:177](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/runtime.py:177>).

## 4. Incoherencias funcionales y mejoras necesarias

### H10 · P2 · La selección del modelo de análisis no expresa una política coherente

**Evidencia:** reproducido que `fallback_allowed=False` en el perfil acaba en `True` y `allow_substitution=True` para la extracción. Por código, la selección automática solo admite Ollama; una selección manual no se valida contra esa allowlist; la comparación toma el primer perfil activo con modelo fijado en lugar del perfil de la nota. Si todos los candidatos automáticos están vetados, `None` devuelve la decisión al Broker. El registro de fallos atribuye el error al modelo solicitado, aunque el Broker haya sustituido el modelo, y no ofrece caducidad ni rehabilitación.

**Cambio:** política de análisis explícita por operación/perfil; catálogo filtrado por capacidades y proveedor autorizado; opción de modelo exacto respetada; atribución al modelo realmente ejecutado; veto por causa/modelo/versión con rehabilitación. No basta ampliar la allowlist a proveedores cloud: debe conservarse la privacidad autorizada.

**Aceptación:** probar modelo manual de otro proveedor, sustitución, veto total, fallo por nota modificada y comparación entre perfiles distintos; mostrar antes del envío qué política se usará.

Referencias: [src/knowledge_orchestrator/services/model_selection.py:26](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/services/model_selection.py:26>); [src/knowledge_orchestrator/services/semantic_maintenance/prompts.py:105](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/services/semantic_maintenance/prompts.py:105>); [src/knowledge_orchestrator/services/semantic_broker.py:79](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/services/semantic_broker.py:79>); [src/knowledge_orchestrator/services/semantic_maintenance/__init__.py:102](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/services/semantic_maintenance/__init__.py:102>).

### H11 · P2 · El fallback de la estrategia automática queda inalcanzable

**Evidencia:** reproducido tras aceptar una tarea como `auto`, con fallback permitido, y devolver `CONSENSUS_QUORUM_NOT_REACHED`: el workflow termina en `ERROR` y no aparece tarea alternativa.

**Causa:** el planificador contempla `auto`, pero la transición que evita cerrar el workflow solo contempla `mixture_of_agents`. Cuando el planificador intenta continuar, encuentra un workflow terminal.

**Cambio:** unificar la condición de fallback y su lista de errores elegibles en un único módulo. **Aceptación:** `auto` y `mixture_of_agents` crean exactamente una alternativa para los mismos fallos permitidos; presupuesto, privacidad y contrato nunca la activan.

Referencias: [src/knowledge_orchestrator/repositories/workflow_repository/estado.py:344](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/repositories/workflow_repository/estado.py:344>); [src/knowledge_orchestrator/services/workflow_planner.py:215](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/services/workflow_planner.py:215>).

### H12 · P2 · Reintentar mezcla configuración nueva y política antigua

**Evidencia:** reproducido. Se cambia el perfil de `public` a `local_only` y se prohíben sustituciones; el reintento conserva `public` y sustituciones permitidas. Solo refresca modelo, temperatura y tokens.

La UI avisa que los cambios afectan a documentos nuevos, por lo que no debe interpretarse como una fuga real demostrada. Sí existe una ambigüedad: el reintento adopta parte del perfil nuevo y conserva otra parte sin presentar la política efectiva.

**Cambio:** ofrecer dos operaciones inequívocas: repetir la petición original o replanificar con una revisión de perfil completa. Mostrar modelo, privacidad, sustituciones y presupuesto efectivos antes de replanificar. **Aceptación:** no generar peticiones híbridas y conservar la revisión de política usada.

Referencias: [src/knowledge_orchestrator/repositories/workflow_repository/control.py:27](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/repositories/workflow_repository/control.py:27>); [src/knowledge_orchestrator/ui/dashboard/configuracion.py:606](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/ui/dashboard/configuracion.py:606>).

### H13 · P2 · La configuración admite ubicaciones que las operaciones no soportan

**Evidencia:** código; el comportamiento entre volúmenes no se ejecutó sobre datos reales. La app permite separar raíz de datos y vault, pero el rechazo mueve la nota desde el vault a `rejected` con `os.replace`. Esa operación puede fallar entre sistemas de archivos. La publicación inicial exige enlaces duros, sin una comprobación previa de compatibilidad al elegir la bóveda. [Contrato de `os.replace`](https://docs.python.org/3/library/os.html#os.replace).

**Cambio:** comprobar capacidades de las ubicaciones al guardar; evitar solapamientos peligrosos entre inbox, trabajo y vault; implementar traslado entre volúmenes mediante copia verificada, intención durable y retirada del origen solo tras confirmar destino, o rechazar explícitamente esa configuración. No sustituir la publicación protegida por una copia no atómica.

**Aceptación:** ensayo con datos en C: y vault en otra unidad, destino sin enlaces duros y disco desconectado. La incidencia de un documento no debe detener el resto ni impedir reiniciar.

Referencias: [src/knowledge_orchestrator/services/path_settings.py:55](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/services/path_settings.py:55>); [src/knowledge_orchestrator/services/publication.py:263](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/services/publication.py:263>); [src/knowledge_orchestrator/services/publication.py:242](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/services/publication.py:242>).

### H14 · P2 · Detectar una edición externa no completa su reconciliación

**Evidencia:** código. `reconcile()` observa hashes y registra `CONFLICT`/`MISSING`; repetirlo no acepta la nueva versión ni relocaliza archivos. La vista previa exige el hash registrado y pide reconciliación. No se encontró en los recorridos revisados una acción equivalente a «incorporar esta edición de Obsidian».

**Cambio:** asistente con diferencias y opciones para adoptar versión humana, localizar nota movida, retirar del índice o conservar conflicto. La adopción debe versionar, recalcular evidencia e invalidar propuestas dependientes. **Aceptación:** editar una nota en Obsidian puede resolverse desde la app, sin modificar SQLite a mano ni sobrescribir el trabajo humano.

Referencias: [src/knowledge_orchestrator/services/knowledge.py:16](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/services/knowledge.py:16>); [src/knowledge_orchestrator/services/knowledge_access.py:120](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/services/knowledge_access.py:120>).

### H15 · P2 · Organización muestra temas, pero no permite gestionarlos

**Evidencia:** código. La pantalla implementa listado y acceso a perfiles. No ofrece crear/editar tema, palabras clave, carpeta, orden o asignación de perfil, aunque los servicios `save_topic()` y `reorder_topics()` existen y la especificación describe esa gestión.

**Cambio:** exponer esas operaciones con validación y vista previa de clasificación. Aclarar si cambiar carpeta afecta solo a documentos nuevos o migra notas existentes. **Aceptación:** crear un tema, asignarle perfil y keywords, cambiar su prioridad y comprobar una captura de ensayo sin consola.

Referencias: [src/knowledge_orchestrator/ui/dashboard/temas.py:20](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/ui/dashboard/temas.py:20>); [src/knowledge_orchestrator/services/topic_service.py:19](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/services/topic_service.py:19>); [Agent_Knowledge_Orchestrator.md:255](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/Agent_Knowledge_Orchestrator.md:255>).

### H16 · P2 · La importación manual promete documentos, pero exige un contrato técnico

**Evidencia:** código y contrato. El selector admite `.md` y copia el archivo al inbox; la ingesta exige frontmatter contractual y sección de transcripción. PRODUCT sí documenta esa restricción, por lo que no es un fallo del validador: es una fricción de entrada que la acción «Importar documentos» no resuelve.

**Cambio:** distinguir «Importar captura compatible» de «Añadir Markdown/texto»; reutilizar la normalización de ingesta API para crear una envoltura válida, con título, origen y vista previa. Conservar siempre el archivo original. Explicar errores junto al documento y enlazar una plantilla.

**Aceptación:** importar un Markdown ordinario permite convertirlo de forma explícita; una captura defectuosa ofrece diagnóstico y corrección sin exigir editar contratos a ciegas.

Referencias: [src/knowledge_orchestrator/ui/dashboard/trabajo_acciones.py:20](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/ui/dashboard/trabajo_acciones.py:20>); [PRODUCT.md:31](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/PRODUCT.md:31>); [src/knowledge_orchestrator/services/api_ingestion.py:21](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/services/api_ingestion.py:21>).

### H17 · P2 · La biblioteca oculta el límite de 500 notas y filtra temas después del recorte

**Evidencia:** código. La consulta devuelve como máximo 500 notas. La pantalla no presenta paginación ni total real y construye los filtros de tema con esas notas ya recortadas. La búsqueda SQL puede encontrar una nota antigua si se conoce un término, pero explorar un tema cuyos documentos estén fuera de ese subconjunto puede no ofrecerlo siquiera como filtro.

**Cambio:** filtros y paginación en consulta, catálogo de temas independiente del resultado y total explícito: «1–100 de 2.530». **Aceptación:** con 501 y 5.000 notas se puede alcanzar la más antigua y un tema ausente de la primera página; el contador no sugiere que el subconjunto es toda la biblioteca.

Referencias: [src/knowledge_orchestrator/ui/snapshots.py:312](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/ui/snapshots.py:312>); [src/knowledge_orchestrator/ui/dashboard/biblioteca.py:181](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/ui/dashboard/biblioteca.py:181>).

### H18 · P2 · Persiste trabajo bloqueante en Tk y reconciliación completa en lecturas frecuentes

**Evidencia:** código; la magnitud de la degradación requiere benchmark. El refresco general consulta trabajo, revisiones, temas y perfiles sincrónicamente. Importar ejecuta `shutil.copy2` en el callback. Seleccionar una afirmación y editar una propuesta también acceden directamente a servicios/repositorios. Una lectura documental o búsqueda puede reconciliar todas las notas, leer sus bytes y abrir transacciones de actualización por nota.

**Impacto:** el uso de hilos en varias pantallas es una mejora real, pero no garantiza que todo el escritorio siga respondiendo con una bóveda grande, disco lento o contención SQLite. El contrato «la UI no accede al filesystem ni SQLite» no se respeta de manera uniforme.

**Cambio:** snapshots y comandos asíncronos coherentes en todas las pantallas; paginación del trabajo; reconciliación incremental con caché e invalidación; evitar actualizar filas que no cambian; aislamiento del polling respecto a lotes de envío largos.

**Aceptación propuesta:** medir retraso del bucle UI con 1.000/10.000 notas y disco degradado; fijar un objetivo de respuesta, por ejemplo p95 menor de 200 ms para interacción simple. No presentar ese objetivo como una medición ya obtenida.

Referencias: [src/knowledge_orchestrator/ui/dashboard/__init__.py:296](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/ui/dashboard/__init__.py:296>); [src/knowledge_orchestrator/ui/dashboard/trabajo_acciones.py:34](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/ui/dashboard/trabajo_acciones.py:34>); [src/knowledge_orchestrator/ui/dashboard/conocimiento.py:160](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/ui/dashboard/conocimiento.py:160>); [src/knowledge_orchestrator/services/knowledge_access.py:25](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/services/knowledge_access.py:25>); [src/knowledge_orchestrator/services/knowledge.py:23](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/services/knowledge.py:23>).

### H19 · P2 · La API exige configuración externa para una tarea básica de administración

**Evidencia:** código. La pantalla permite iniciar/detener el listener y ver consumidores, pero las credenciales se cargan de `KO_API_CLIENTS`. Sin esa variable, el usuario debe salir del flujo de escritorio para configurar acceso. La API existe: no debe seguir describiéndose como una función futura.

**Cambio:** alta/revocación de consumidores desde la UI, scopes comprensibles, credencial mostrada una sola vez y almacenamiento protegido. Añadir comprobación local y ejemplos copiables que no expongan secretos en registros. **Aceptación:** crear un consumidor de solo lectura y revocarlo sin consola; comprobar que no puede ingerir ni aprobar.

Referencias: [src/knowledge_orchestrator/api/auth.py:47](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/api/auth.py:47>); [src/knowledge_orchestrator/ui/dashboard/servicios.py:224](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/ui/dashboard/servicios.py:224>).

### H20 · P2 · Los embeddings no forman un circuito operativo completo

**Evidencia:** código y contratos. Hay almacenamiento, comparación y endpoint que acepta vectores, pero `embedding_request()` solicita números a una tarea de chat. El procesador semántico solo implementa `EXTRACT` y `COMPARE`; no se encontró un productor en ejecución que programe e integre embeddings automáticamente. El propio contrato reconoce que no es embedding nativo.

**Cambio:** decidir el alcance: declarar búsqueda léxica con capacidades vectoriales experimentales, o implementar una tarea de embedding real con identidad de modelo/proveedor, dimensiones, versionado y reindexado. Validar recuperación sobre un conjunto de consultas y relevancias antes de usar similitud para proponer cambios.

**Aceptación:** una nueva afirmación obtiene su vector por el circuito de producción, se recupera con el mismo espacio de embeddings y se excluye cuando cambia la versión del índice. No presentar una lista de números inventada por chat como equivalencia a ese circuito.

Referencias: [src/knowledge_orchestrator/services/semantic_maintenance/prompts.py:132](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/services/semantic_maintenance/prompts.py:132>); [src/knowledge_orchestrator/services/semantic_maintenance/__init__.py:162](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/services/semantic_maintenance/__init__.py:162>); [src/knowledge_orchestrator/services/knowledge_access.py:154](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/services/knowledge_access.py:154>); [Data_Contracts.md:917](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/Data_Contracts.md:917>).

### H21 · P2 · Algunas opciones distintas producen el mismo comportamiento

**Evidencia:** código. Los modos «Dividir el documento localmente» y «Procesar documentos extensos por bloques» terminan usando división local y `long_context='fail'` en la petición. Aun así, la UI condiciona la segunda opción a una capacidad del Broker que no utiliza en ese recorrido. También debe explicarse qué pasos son elegibles para consenso: cambiar la estrategia no cambia automáticamente `multitasking_steps`.

**Cambio:** mostrar únicamente decisiones con efecto real o etiquetar sus límites. Separar modo de documento y estrategia de cada paso con una vista de «política efectiva». **Aceptación:** cada alternativa visible cambia un comportamiento demostrable; las restricciones de la UI corresponden al camino ejecutado.

Referencias: [src/knowledge_orchestrator/ui/dashboard/configuracion.py:34](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/ui/dashboard/configuracion.py:34>); [src/knowledge_orchestrator/ui/dashboard/configuracion.py:576](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/ui/dashboard/configuracion.py:576>); [src/knowledge_orchestrator/services/prompting.py:155](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/services/prompting.py:155>); [src/knowledge_orchestrator/services/prompting.py:100](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/services/prompting.py:100>).

### H22 · P2 · La documentación vigente se mezcla con diseños y checkpoints históricos

**Evidencia:** contradicciones concretas. PRODUCT niega que exista la API documental; README y el código sí la incluyen. La especificación del agente excluye RSS/conectores automáticos, pero ya existen Web/RSS. El contrato mantiene una deuda sobre comparación literal de versión 2.8 que el worker ya ha corregido. La sección de extracción sigue diciendo que offsets son obligatorios, mientras 0.3.3 los calcula cuando es necesario. Coexisten diferentes recuentos de pruebas y pendientes visuales correspondientes a fechas distintas.

**Cambio:** una matriz única y breve de capacidades actuales, limitaciones y evidencia por versión. Mantener el historial con fecha y aviso de que no es normativo. Generar los contratos publicables desde esquemas cuando sea posible. Distinguir capacidad implementada, probada con simulación y validada de extremo a extremo.

**Aceptación:** README, PRODUCT, contratos y UI describen el mismo comportamiento; cada requisito relevante enlaza una prueba y un criterio de aceptación. Conservar la honestidad de CURRENT_STATE sobre la extracción real pendiente.

Referencias: [PRODUCT.md:36](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/PRODUCT.md:36>); [Agent_Knowledge_Orchestrator.md:539](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/Agent_Knowledge_Orchestrator.md:539>); [Data_Contracts.md:1061](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/Data_Contracts.md:1061>); [Data_Contracts.md:1048](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/Data_Contracts.md:1048>); [src/knowledge_orchestrator/worker/broker_worker.py:238](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/worker/broker_worker.py:238>).

### H23 · P2 · El backup no es todavía una recuperación integral del producto

**Evidencia:** código y alcance documentado. `--backup` genera una copia SQLite consistente, lo que es correcto. No constituye una copia restaurable del conjunto de fuentes, notas, configuraciones y recibos del puente; tampoco se encontró una operación de restauración integral en la interfaz/CLI revisadas. No es un incumplimiento de una promesa de backup completo, sino una carencia operativa para un producto cuyo estado depende de varios soportes.

**Cambio:** definir copia coherente y restauración por manifiesto con hashes; incorporar fuentes y referencias a bóveda, configuración no secreta y estrategia para recibos. Tratar credenciales DPAPI como ligadas al usuario, con reconexión explícita al migrar de equipo. Añadir comprobación previa de compatibilidad del almacenamiento y una guía de recuperación.

**Aceptación:** recuperar en una raíz vacía, verificar inventario/hash, abrir notas y reanudar una intención pendiente sin duplicar ni sobrescribir cambios humanos. Ensayar también el caso de backup sin vault disponible.

Referencias: [src/knowledge_orchestrator/services/operations.py:84](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/services/operations.py:84>); [src/knowledge_orchestrator/app.py:24](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/app.py:24>); [obsidian-bridge/README.md:61](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/obsidian-bridge/README.md:61>).

## 5. Observaciones técnicas adicionales

- **Firma incompleta de idempotencia semántica.** Sonda reproducida: cambiar `max_cost_usd` modifica la petición pero conserva su clave, porque la firma solo incorpora prompt, schema, modelo y tokens. Actualmente el flujo habitual no proporciona un coste semántico distinto; es un defecto latente al usar el parámetro disponible. Calcular la firma del contenido canónico relevante completo, separando identidad lógica de identidad de intento. Referencia: [src/knowledge_orchestrator/services/semantic_maintenance/prompts.py:93](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/services/semantic_maintenance/prompts.py:93>).
- **Conocimiento «sin resultados» y conocimiento «sin analizar» necesitan mensajes distintos.** La pantalla de afirmaciones vacía sugiere cambiar filtros; si la extracción ha fallado, la acción útil es recuperar ese análisis. Mostrar notas publicadas, notas indexadas, pendientes, fallidas y fecha de actualización, con navegación directa al fallo. Referencia: [src/knowledge_orchestrator/ui/dashboard/conocimiento.py:152](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/ui/dashboard/conocimiento.py:152>).
- **Confianza porcentual no es precisión factual.** La revisión presenta el porcentaje del modelo destacado y sí conserva advertencias sobre su significado. Mantener esas advertencias cerca del porcentaje y dar mayor protagonismo al fragmento original, fecha y discrepancias. No usar confianza como sustituto de evaluación de calidad. Referencia: [src/knowledge_orchestrator/ui/dashboard/revision.py:240](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/src/knowledge_orchestrator/ui/dashboard/revision.py:240>).
- **Puente: recuperación y mantenimiento operativo.** Su diseño conserva intenciones cuando está desconectado y reconoce límites de recibos. Completar reintento seguro sin exigir reiniciar toda la aplicación, procedimiento de mantenimiento del journal y ensayos dentro del editor real. Estas son limitaciones reconocidas, no evidencia de sobrescritura observada. Referencia: [obsidian-bridge/README.md:54](<D:/Desarrollo/Proyectos TFM/Knowledge_Orchestrator/obsidian-bridge/README.md:54>).
- **Pruebas de seguridad: conservar los controles existentes.** La API usa autenticación y scopes; el cliente del puente limita destino e identidad de bóveda; los conectores fijan IP pública y acotan tamaño/redirecciones; hay redacción de errores. No se ha demostrado una vulnerabilidad remota nueva en esta revisión. Estos controles no compensan los errores de política de producto de H01/H08/H10.

## 6. Recorrido de usuario: qué debe cambiar

| Paso | Estado observado en código/pruebas | Cambio de experiencia necesario |
|---|---|---|
| 1. Primera apertura | Dependencia de rutas predeterminadas antes de UI | Asistente de configuración que funcione sin Broker ni unidad externa |
| 2. Configurar procesamiento | Controles legibles, pero varias garantías no se aplican completamente | Presentar política efectiva, alcance del coste y modelo por tipo de tarea |
| 3. Añadir documentos | Selector simple; formato contractual obligatorio | Conversión guiada de Markdown normal y errores corregibles |
| 4. Seguir un documento | Estados y cronología ya útiles | Separar publicación, indexación y disponibilidad para consultas |
| 5. Cancelar o recuperar | Recuperación parcial y cancelación de una tarea | Acciones sobre el documento completo; reintentar análisis en su contexto |
| 6. Revisar | Comparación y versiones sólidas para cambios semánticos | Añadir aprobación de nota inicial; priorizar evidencia primaria |
| 7. Consultar biblioteca | Vista previa y apertura en Obsidian; recorte de 500 | Paginación real, búsqueda consistente y explicaciones de falta de evidencia |
| 8. Editar en Obsidian | Conflicto detectado correctamente | Resolver/adoptar/volver a indexar sin consola |
| 9. Organizar conocimiento | Temas visibles, gestión ausente | Edición de temas, reglas, prioridad y perfil |
| 10. Compartir por API | API funcional; consumidores por entorno | Administración de acceso desde UI y prueba local |
| 11. Automatizar y recuperar | Gobernanza significativa; ciclo real no acreditado en esta auditoría | Activar sobre un núcleo validado y verificar restauración completa |

Para el siguiente ensayo visual: 1080×680 y otras resoluciones habituales, escalado Windows de 125/150/200 %, teclado completo, foco tras refrescos, diálogos largos, lectores de pantalla, tablas con muchos elementos y estados de error. **No se afirma que esos controles hayan fallado ahora:** son las comprobaciones visuales y de accesibilidad que faltan en esta auditoría.

## 7. Plan de mejora ordenado por dependencias

### Entrega A · Recuperar control del trabajo

Corregir H01–H05. Unificar comandos de aprobar, cancelar y reintentar alrededor del documento/workflow; aislar fallos por elemento; añadir estados separados de publicación y análisis. Incorporar las sondas reproducidas como regresiones permanentes, con aserciones sobre ausencia de efectos no autorizados.

**Cierre verificable:** ningún documento se publica contra su política, ninguna cancelación deja nuevos envíos y una nota problemática no impide usar la app.

### Entrega B · Hacer fiable el procesamiento y el conocimiento

Corregir H06–H08 y H10–H12. Introducir presupuesto compartido, síntesis jerárquica y políticas versionadas completas. Cambiar el origen de la evidencia a capturas inmutables. Preparar un corpus de evaluación con citas y relaciones esperadas, errores de modelo, contradicciones, fechas y documentos extensos.

**Cierre verificable:** el circuito real captura → nota → claims → propuesta → consulta funciona con evidencia correcta y coste acotado. Publicar precisión/cobertura/latencia por modelo y tipo de tarea. No basta con una nota bien redactada ni con tests que sustituyen la respuesta del modelo por JSON perfecto.

### Entrega C · Completar los recorridos cotidianos

Corregir H14–H19 y H21: resolver cambios de Obsidian, gestionar temas, importar texto, paginar, explicar estados vacíos y administrar consumidores API. Sacar las operaciones de disco/DB pendientes del hilo Tk y medir antes/después con corpus representativos.

**Cierre verificable:** una persona puede configurar, importar, revisar, cancelar, reparar, organizar y consultar usando solo la aplicación.

### Entrega D · Operación, documentación y distribución

Corregir H09/H13/H20/H22/H23 según el alcance decidido. Ensayar instalación en Windows limpio, almacenamiento admitido, backup/restauración y puente dentro de Obsidian. Mantener una matriz de compatibilidad y un procedimiento de actualización que preserve configuración y recibos.

**Cierre verificable:** reinstalar o recuperar una máquina no exige reconstruir manualmente relaciones entre notas, capturas y SQLite; la documentación refleja la versión entregada.

## 8. Cambios de arquitectura recomendados

No se justifica una reescritura completa ni cambiar Tkinter únicamente por estos hallazgos. La mayor parte del valor está en corregir límites de responsabilidad y contratos internos:

1. **Ciclo documental explícito:** captura, procesamiento, borrador, publicación, extracción, indexación y revisión deben ser estados distinguibles, con errores y comandos propios.
2. **Ejecución gobernada por workflow:** cancelación y costes pertenecen al documento completo; cada tarea mantiene identidad, intento y recibos.
3. **Política efectiva inmutable por intento:** modelo, proveedores, privacidad, presupuesto, sustituciones, límites y revisión se congelan juntos; replanificar produce otra revisión.
4. **Evidencia primaria separada de redacción:** conservar citas de la captura original y sus derivaciones; un resumen no puede aumentar por sí mismo la fuerza de su evidencia.
5. **Lecturas/UI desacopladas:** snapshots paginados y comandos asíncronos; la reconciliación incremental no debe convertirse en una escritura masiva cada vez que se abre una nota.

La persistencia por intenciones, hashes, revisiones, comprobaciones de base y recibos es una inversión aprovechable. Hay que conservarla al corregir las rutas anteriores.

## 9. Regresiones y aceptación pendientes

| Grupo | Casos mínimos que añadir |
|---|---|
| Control humano | Aprobación inicial requerida, repetida, denegada y tras reinicio; resultado modificado después de abrir la revisión |
| Cancelación | Documento con tareas READY/QUEUED/PROCESSING; confirmación tardía; resultado que llega tras cancelar; reinicio |
| Recuperación | Nota ausente/renombrada/ilegible; un trabajo malo entre trabajos válidos; puente desconectado |
| Contratos IA | JSON con tipos inesperados; citas inventadas; varias ocurrencias; respuestas vacías y parcialmente válidas |
| Reintentos | Cambio de modelo, política, prompt y presupuesto; petición exacta repetida; identidad nueva para contenido distinto |
| Contexto/costes | 1/10/100 fragmentos, varios niveles de reducción, cambio de modelo y contabilidad agregada |
| Evidencia | Invención en resumen, cita original verificable, contradicción temporal y edición humana posterior |
| UI/datos | 501/5.000 notas, tema fuera de página inicial, búsquedas, operaciones lentas y retraso de eventos |
| Entorno | Windows limpio, ausencia de Y:, discos distintos, filesystem incompatible, backup/restauración |
| Integración real | Broker real con modelos declarados, Obsidian abierto editando la misma nota, respuesta perdida y reversión |

## 10. Evidencia reproducible y límites del dictamen

Los resultados completos de las 11 sondas se adjuntan en `probe-results.json`. Se incluyen casos sintéticos deliberados; no describen datos ni gastos reales del usuario. La sonda de revisión humana demuestra la falta de barrera en el Orchestrator; no intenta atribuir al Broker remoto una política no comprobada. La de evidencia demuestra aceptación de una frase introducida en la salida simulada; no mide la tasa real de alucinaciones de un modelo.

Las pruebas globales ejecutadas usaron el comando de escritorio ya previsto por el proyecto (`tools/verify_desktop.py discover -s tests -q`), además de las dos suites Node del puente, Ruff y mypy. No se abrió la base personal ni se activaron sus automatizaciones. No se afirma haber inspeccionado cada línea de los 151 módulos, realizado un pentest o certificado accesibilidad: es una auditoría transversal con seguimiento de flujos críticos, revisión documental y reproducción dirigida.

**Decisión recomendada:** tratar 0.3.3 como una base funcional en estabilización. La prioridad es que las garantías visibles —aprobar, cancelar, limitar coste, recuperar y citar— sean ciertas de extremo a extremo. Con ese núcleo validado, la gobernanza y la interfaz existentes pueden aportar valor sin una reescritura general.
