# Estado vigente de Knowledge Orchestrator

Incremento 41, **27 de octubre de 2026 — 0.5.11, KO deja el control de coste al Broker**. A petición del usuario se elimina la bolsa de presupuesto por documento: `claim_submission` ya no rechaza envíos con `DOCUMENT_BUDGET_EXHAUSTED`, el planificador ya no reparte el tope entre fragmentos, reducciones y síntesis (`split_budget` y `_remaining_budget` eliminados) y cada petición lleva el `max_cost_usd` del perfil, que hace cumplir el Broker. Ajustes lo llama ahora «Coste máximo por petición (USD)». Las columnas `budget_usd`/`budget_reserved_usd` siguen escribiéndose pero ya no deciden nada. Pruebas ajustadas en `test_audit_2026_09_27.py` y `test_presupuesto_2026_10_26.py`.

Incremento 40, **27 de octubre de 2026 — 0.5.10, «presupuesto agotado» sigue tras 0.5.6**. Tres documentos
de «Necesitan atención» fallaban en cada reintento. (A) Dos de una sola petición: `TASK_TIMEOUT` sin
`progress` (el Broker NO informa coste en ese fallo; 0.5.6 lo suponía), así que la reserva prudente de
0,05 USD ocupaba la bolsa entera para siempre. Su petición lleva `cloud_allowed: false` y solo `ollama`:
no puede costar nada. `request_cost` trata ya `cloud_allowed: false` como `local_only` (coste 0); con nube
la prudencia no cambia. (B) Uno troceado: su alternativa (`…:fallback`) al reintentarse cortaba la clave por
`:manual-`, perdía el sufijo y repetía la clave de la original → HTTP 409 `IDEMPOTENCY_CONFLICT`.
`retry_failed_task` conserva ahora `:fallback`. Pruebas en `test_presupuesto_2026_10_26.py` (3 nuevas, fallan
sin el arreglo); `test_split_document_never_reserves_more_than_its_budget` pasa a perfil con nube.
(C) **Proveedores configurables.** `allowed_providers` y `cloud_allowed` eran los valores por defecto del
código (`("ollama",)`, sin nube) y no salían en Ajustes: «Privacidad: público» no abría nada. Ajustes tiene
ahora «Proveedores permitidos», una casilla por proveedor del catálogo (`UiSnapshotService.providers()`, local
si `deployment == "local"`); `cloud_allowed` se deduce de si hay alguno de nube marcado (`provider_policy`,
que también impide nube con «Solo local»/«Confidencial» y un modelo fijado de un proveedor no marcado). El
`PanedWindow` se reajusta al rellenar las casillas (si no, cortaba «Modelos apartados por fallos…»). La
extracción de afirmaciones sigue con ollama y `local_only` (`JSON_TASK_PROVIDERS`): no se ha tocado.
Manual (cap. 17) y su captura actualizados.

Incremento 39 (anterior), **27 de octubre de 2026 — 0.5.9, la Biblioteca busca sin tildes**. Buscar «Què es el Data
Scienc» no encontraba «Qué es el Data Science…»: el `LIKE` de SQLite distingue tildes. `_library_filter`
compara ahora con `normalize_search_text` (sin tildes, mayúsculas ni signos) registrada como `ko_fold`
en la conexión de lectura; de paso `%` y `_` dejan de actuar como comodines.

Incremento 38 (anterior), **27 de octubre de 2026 — 0.5.8, título de apuntes con plantilla**. Los apuntes que
empiezan con un encabezado «## Título» y el título real en la línea siguiente se importaban todos como
«Título». `markdown_import.detect_title` toma ahora la línea de debajo cuando el primer encabezado es solo
«Título»/«Title». Los 9 apuntes ya cargados se retitularon (captura, nombre del fichero, cabecera y hash)
y su análisis en cola se rehízo; copia previa en `I:/KO-datos/backups/antes-retitular-apuntes-20261027.db`.

Incremento 37 (anterior), **26 de octubre de 2026 — 0.5.7, apuntes propios publicados tal cual**.
Importar unos apuntes ya hechos los mandaba al Broker para resumirlos otra vez. El diálogo «Convertir
documentos» tiene ahora la casilla «Ya son apuntes míos: publicarlos tal cual»: la captura lleva
`own_notes: true` (`domain/sources.is_own_note`), el planificador crea un workflow sin tareas
(`plan.strategy = own_note`; la tabla sigue diciendo `single` con 1 paso por sus CHECK) y lo cierra con el
texto original; la nota sale con `note_origin: own_note`. Si se corta entre crear y cerrar,
`advance_workflow` lo cierra al recuperar. Las afirmaciones se extraen igual pero sin fuente (la fuente
sería la propia nota y todo saldría «respaldado»), y la migración 030 añade `knowledge_claims.claim_origin`
(`DOCUMENT` | `OWN_NOTE`). Pesan menos: no generan candidatos de cambio en otras notas, `OWN_NOTE_WEIGHT`
(0,5) rebaja su bm25 y su similitud por vectores, y el prompt de consulta prefiere el claim del documento
si se contradicen. La UI de Afirmaciones las etiqueta «Apunte propio». Pruebas en
`test_apuntes_propios_2026_10_26.py` (las de peso y fuente fallan sin el arreglo).

Incremento 36, **26 de octubre de 2026 — 0.5.6, documentos rechazados «por coste» con modelos gratuitos**.
Siete documentos con perfil `public` murieron al reintentarlos con `DOCUMENT_BUDGET_EXHAUSTED`, aunque el Broker
informó coste 0,0 en los 6502 registros de la base. No lo rechazaba el Broker: era la bolsa del documento
(auditoría H08), que no recuperaba lo reservado. (A) Tras un fallo ejecutado (`TASK_TIMEOUT`, `BUDGET_EXCEEDED`),
`coste_real` solo leía `result.usage.cost_usd`, que es `null` al fallar; ahora usa también
`progress.cost_actual_usd`, que el Broker informa en toda tarea. Sin ningún dato sigue reservando con prudencia
(garantía para proveedores de pago intacta). (B) El reintento automático por tokens reabría la tarea sin liquidar
el intento cortado. (C) «Reintentar documento» reabría a la vez una tarea y la alternativa que ya la sustituía, y
ambas se disputaban la bolsa; ahora solo se reabre la última de la cadena. Pruebas en
`test_presupuesto_2026_10_26.py` (5 de 6 fallan sin el arreglo; la de prudencia pasa en ambos casos). Los 5
documentos de una sola petición se liberaron y se reenviaron con el propio `release_reservation`, con una copia
previa de la base. Los dos troceados esperan a que su síntesis original, aún en cola del Broker, termine.

Incremento 35, **26 de octubre de 2026 — 0.5.5, la ventana se quedaba bloqueada**.
Medido con py-spy sobre la app en uso: el 96 % del hilo de Tk estaba en `UiSnapshotService.work_items`,
que tardaba 6–12 s con la base real (765 documentos, ~2000 tareas de ~75 KB) y el refresco repetía cada 2 s.
La subconsulta «última tarea del documento» recorría `tasks` entera por cada documento (`SCAN latest`).
(A) Migración 029: índice `idx_tasks_capture_latest`; la consulta baja a 0,07 s con el mismo resultado
(comprobado sobre copia de la base real). (C) `ui/lecturas_fondo.BackgroundSnapshots` envuelve el servicio
de lecturas: en el refresco periódico devuelve el último resultado y lo renueva en un hilo aparte; arranque,
F5 y las acciones siguen leyendo en el acto. Un fallo en segundo plano se anuncia una vez y se sigue
mostrando lo último bueno. Pruebas en `test_fluidez_ui_2026_10_26.py` (fallan sin cada arreglo).

Incremento 34, **25 de octubre de 2026 — 0.5.4, apuntes cortados que el Broker daba por buenos**.
El Broker devuelve `completed` sin `done_reason` cuando el modelo agota `max_output_tokens`
(ornith, nemotron-lightning) o su ventana (modelos de LM Studio de 8192). `study_notes_quality_error`
solo veía cortes que acababan en un título. Ahora, si la petición pide «## Cobertura» y el paso es
final (no `reduce_*`), un texto de ≥500 caracteres sin esa sección es `TRUNCATED_OUTPUT`. También lo
es una respuesta con `tokens_output == max_output_tokens` aunque tenga «Cobertura» (lfm2 repetía el
formato entero 3–4 veces hasta el tope); en ese caso entra en el reintento con el doble de presupuesto.
Igualdad y no `>=`: el Broker informa a menudo más tokens que el límite (p. ej. 21182/7500 con
qwen3-coder-next) en notas completas. Medido sobre las 382 notas publicadas: 44 detectadas, ninguna
con su sección final (se admiten «### 21. Cobertura», «**## Cobertura**», «## Cobertura de…»).
Las 46 cortadas y 3 bucles se rechazaron y replanificaron con `PublicationService.reject` + `reprocess`.
Rechazar una nota publicada no cierra sus propuestas de mantenimiento: se cerraron 15 a mano con
`semantic_maintenance.reject` (la UI de Revisión no filtra por estado de nota). No hay botón para
reprocesar una nota publicada. Pruebas en `test_output_quality.py` y `test_model_budget.py`.

Incremento 33, **21 de octubre de 2026 — 0.5.0, índice de notas y recuperación (Broker 2.12)**.
ChatyGPT mandaba al Broker todas las notas en cada pregunta (89 notas, ~240k tokens, 20 min y
`TASK_TIMEOUT`). El Broker 2.12 trae lotes de embeddings (`content.inputs`, hasta 64) y un carril
propio que no espera al chat. KO ahora indexa y recupera.

| Hallazgo | Corrección |
|---|---|
| Sin forma de saber qué notas tocan una pregunta | `services/note_index.py` + migración 028: fragmentos de ≤1.200 caracteres (FTS5) y vectores float32 del modelo elegido en Ajustes → «Índice para preguntas» (solo locales). `POST /retrievals` + `GET /retrievals/{id}` + `GET /index` (permiso `read`). Sin tope de notas: por palabras (término en ≤5 % de los fragmentos, y con similitud ≥ media+1σ), por significado (≥ media+2σ), fusión por rango recíproco; las notas sin indexar van aparte (`tests/test_note_index.py`) |
| `kind: "embedding"` rechazado por el espejo del contrato | Se acepta cualquier carril y un embedding se valida por sus vectores (`embedding_vectors`), no por `assistant_content` |
| La petición de embedding de KO nunca funcionó (`json_schema: null` → 422 del Broker) | Sin `json_schema` (2.12) y constructor de lotes `embedding_batch_request` con `target_model` exacto |
| 18 extracciones del 19-oct murieron por `disk I/O error` (base en Drive) y quedaron como fallo definitivo | `OperationalError` pasajero deja el trabajo para el ciclo siguiente; la reintegración no duplica (ON CONFLICT) |
| 2 extracciones de 25 afirmaciones tumbadas porque el modelo puso «S6»/«N4» en `observed_at` | La fecha opcional inválida se descarta y el prompt explica el campo |

Prueba real con una copia de la base (103 notas):
- **Indexado:** 1.755 fragmentos con `bge-m3` en ~3,5 min, en lotes de 64, sin un solo fallo.
- **Recuperación:** 3–5 s por pregunta. «Explícame cómo usar MCP» → 11 notas con «¿Usas MCP?» la primera
  (con el primer umbral del 20 % salían 66; medido y corregido).
- **De punta a punta:** ChatyGPT 0.4.18 → `/retrievals` → 11 notas → Broker, `map_reduce` en 2 trozos (antes 7)
  y respuesta completa y citada.
- **Extracciones:** las 22 fallidas se reintentaron en la base real, con copia previa en
  `I:\KO-datos\backups\antes-reintento-extracciones-20261021-203621.db`.

Pruebas: la batería completa da 649 de 650. La única que fallaba fijaba la versión del contrato en 2.10. Ruff y mypy limpios.

Incremento 32, **19 de octubre de 2026 — 0.4.5, base fuera de Google Drive y copia periódica**.
Uso real con ChatyGPT consultando la API. Con la raíz de datos en `Y:\Mi unidad\...` (Google Drive)
pasaba esto:
- cada llamada a la API tardaba 4–5 s;
- `GET /documents/{id}` devolvía 500 de vez en cuando;
- un `sqlite3.OperationalError: disk I/O error` en la primera lectura tras el arranque mató el refresco de
  la ventana: «Documentos» vacío y reloj parado. El traceback solo estaba en la consola.

| Hallazgo | Corrección |
|---|---|
| Un fallo en un paso de `_refresh` cancelaba el siguiente `after()` para siempre | Cada paso del refresco va protegido; el fallo queda en el registro con su traza, la barra de estado lo dice y se reintenta a los 2 s (`test_a_failed_read_does_not_stop_the_periodic_refresh`, que falla con el código anterior) |
| La seguridad de los datos dependía de tener la base en Drive | `worker/backup_worker.py`: si `paths.json` trae `backup_dir`, cada 6 h deja allí la copia integral restaurable y conserva 10. No se activa con `--root`/`KO_ROOT`. `PipelinePathStore.save` conserva `backup_dir` (`tests/test_copia_periodica.py`) |
| Traslado de la raíz de datos sin procedimiento | Manual 18.2: `--full-backup` → `--restore --root` (reescribe las rutas) → copiar `failed`, `logs`, `state\credentials` y `broker_connection.json` → `data_root`. Los datos del usuario se trasladaron así a `I:\KO-datos`: 300 rutas reescritas, mismas filas en todas las tablas e `integrity_check` correcto. El origen en Drive queda intacto |
| La API había que iniciarla a mano en cada sesión; ChatyGPT fallaba con «no responde» con la ventana abierta | `ApiServerController.autostart()`: tras el arranque, si «Iniciar al abrir la aplicación» está marcada (lo predeterminado) y hay consumidores, se inicia en el último puerto usado. Preferencias en `state/api_settings.json` (`tests/test_api_autostart.py`). La propuesta de hacerlo desde AI OS Core se descartó: Core no tiene canal hacia las apps |
| Papeles de KO, Obsidian y Drive confusos para el usuario | Manual: capítulo 1 «Cómo encajan…», 15.3 ChatyGPT, filas nuevas en 19 y 20. Corregido el flujo «Dar acceso a otra aplicación», que ponía Iniciar API antes de crear el consumidor. `build_pdf.py` toma la versión del código |

Pruebas:
- Las tres pruebas nuevas pasan y ruff y mypy están limpios.
- La batería completa da 625–626 de 627. Los 1–2 fallos son distintos en cada ejecución y todos ocurren al
  crear `tk.Tk()` («couldn't read file …/tk8.6/…tcl»), antes de llegar al código de KO. Repetidas por
  separado, pasan.

Incremento 31, **17 de octubre de 2026 — 0.4.2, auditoría humana de UI del 14-oct**
(`D:\Desarrollo\docs\Pruebas\Auditoria_KO_2026-10-14`). Regresiones en `tests/test_auditoria_2026_10_14.py`
(comprobado que las de estilo, panel vacío y fuentes fallan con el código anterior). Verificado además en la
ventana real con el Broker real (sandbox aislado). 615 pruebas, Ruff y mypy limpios; ejecutable 0.4.2 regenerado: enviar → cancelar → «Volver a procesar» → de nuevo en la cola
del Broker, duplicado visible, vista vacía, diálogo de fuente y API; 0 fallos y capturas revisadas.

| Hallazgo | Corrección |
|---|---|
| I-01 Botones deshabilitados idénticos a los activos | El estado deshabilitado gana al foco en todos los estilos de botón: sin anillo acento, fondo de superficie y texto tenue |
| I-01b «Reintentar» de un cancelado no hacía nada | «Volver a procesar»: replanifica una revisión nueva (clave idempotente nueva) con el perfil actual |
| I-01c «Aplicar cambio» sin puente, sin explicación | Motivo visible junto al botón («No se puede aplicar. Para modificar notas… hace falta el puente de Obsidian…») |
| I-02 Bloque «No hay documentos en esta vista» con acciones sin selección | Sin documento no se muestra bloque de incidencia ni acciones |
| I-03 «Finalizados» contaba cancelados | Pestaña propia «Cancelados» (cancelados, rechazados y borradores descartados) |
| I-04 Duplicados solo visibles en disco | Incidencia «Ya importado» en «Necesitan atención» que nombra el original; evento en la cronología del original |
| I-05 El importador rechaza rutas con «/» | Lo hace el diálogo común de Windows (nuevo y clásico, medido con pywinauto). Mientras está abierto, un hilo cambia «/» por «\» en su campo «Nombre» (salvo URLs); además se corrige la ruta entrecomillada que Tk devolvía pegada a la carpeta abierta. Verificado en la ventana real con la ruta de la auditoría (espacios, corchetes, ñ) hasta Documentos. Cubre también «¿Dónde está ahora la nota?» y el selector de carpetas de Ajustes (verificado: sin corrección «D:/tmp» se rechaza, con ella se elige). Extra: «Importar desde rutas…» para varias rutas de carpetas distintas |
| I-06 «Editar propuesta» no modal y sin Cancelar | Modal, con «Cancelar» y Escape; igual «Añadir fuente» y «Nuevo consumidor…» |
| I-07 Fuente guardada con URL inválida | No era falta de validación: el diálogo traía «Nueva fuente · https://example.org» rellenos. Ahora empieza vacío, exige nombre y URL y explica el error de URL |
| I-08 «broker:comparison» y fechas ISO en trazabilidad | Autor en palabras («análisis automático del Broker») y fecha local |
| I-09 «generating» en el mensaje | Fases del Broker traducidas; una desconocida dice «El Broker lo está procesando» |
| I-10 OK/Cancel en inglés | `simpledialog` sustituido por un diálogo propio «Aceptar/Cancelar» (los `messagebox` nativos siguen el idioma de Windows) |
| I-11 Aviso «Falta la credencial» mientras se pega el token | Se actualiza al escribir |
| I-12 Afirmaciones cortadas sin «…» | Recorte con elipsis al ancho real de la columna, también al redimensionar |
| I-13 Diálogos en la esquina de la pantalla | Todo diálogo transitorio aparece centrado sobre la ventana |
| I-14 Teclado en «Nuevo consumidor…» | Enter activa el botón con foco (en toda la app) y crea desde el nombre; foco visible en botones de acento |
| I-15 «50 vigentes» frente a 53 indexadas | El resumen cuenta las retenidas («3 retenidas hasta resolver un cambio pendiente en su nota») y el detalle explica por qué |
| OBS-LOG Log solo con HTTP | `EventLogWorker` vuelca la tabla `events` a `orchestrator.log` (INFO, sin `details_json`) |
| SOS-01 Cuarentena en `processing/` | Reproducción con vigilancia continua (cada 100 ms) repitiendo lo que hizo el auditor en la ventana real (ficheros rotos en cuarentena, sus rutas tecleadas con «/» en el diálogo de importación): ninguno pasó por `processing/`. Por código no puede ocurrir: `.error.json` solo se escribe dentro de `failed/` (`_validate_managed_paths`) y nada mueve de `failed/` a `processing/`. Si volviera a verse, ahora queda en el log (OBS-LOG) |
| I-16 Sin UI Automation | `ui/accesibilidad.py`: al recibir foco, cada control pasa el foco de Windows a su ventana y se anota por MSAA Dynamic Annotation (rol, nombre, valor, estado); los campos toman el nombre de su etiqueta y las listas anuncian la fila elegida. Verificado con UIA en la ventana real recorriendo con Tab («Tree · Documentos», «Button · Revisión», «Edit · URL», «ComboBox · Tipo») y con el teclado intacto (mismo orden de Tab, se escribe y se pulsa igual). **Probado con NVDA 2025.3.1 real** (copia portátil, sintetizador silencioso, log IO): sin la capa solo decía «panel»; con ella, «Documentos, árbol, Informe trimestral…», «Enviar ahora, botón», «Nombre, edición», «Tipo, cuadro combinado, Web». La prueba destapó que el buscador se anunciaba con el código del icono: corregido. Además, Tab entraba en controles de las páginas ocultas (se apilaban con `tkraise`): ahora `_show_page` oculta las demás con `grid_remove` y el ciclo de Tab recorre solo la página visible, pestañas de filtro incluidas |

**Escenarios pendientes de la auditoría (§6), ejecutados el 17-oct en la ventana real** (bóveda aislada con el editor de notas de las pruebas en lugar del puente): P-02 revisión en lote aplicada por el worker; P-10 «Decisión y publicación» muestra lote y publicación; P-01 reversión preparada y confirmada (nota restaurada, la otra intacta); P-03 evaluación con política; P-08 «Cerrar incidencia»; P-07 fichero corregido reimportado; P-05 fuente RSS real (BBC, 27 novedades); P-09 `--restore` con el ejecutable (se niega sin `--root` y sobre carpeta con datos; restaura en vacía). 0 fallos y 0 excepciones. P-04 con **Obsidian 1.12.7 real** (perfil y bóveda aislados, complemento activado por CDP): conexión guardada desde Ajustes, «Aplicar cambio» activo sin aviso, Obsidian muestra el cambio, la reversión lo restaura y el complemento deja sus recibos APPLIED. P-06 con **NVDA 2025.3.1 real** (ver I-16). Todos los escenarios de §6 ejecutados.

Incremento 30, **8–9 de octubre de 2026 — 0.4.1, prueba de uso real con la ventana y el AI Broker**.
Recorridos automatizados sobre la ventana real (clics en los botones, diálogos interceptados y
capturas), con el Broker real (192.168.1.52) y carpetas aisladas. **594 pruebas, Ruff y mypy (161
archivos) limpios; ejecutable 0.4.1 regenerado** (sin instalador: falta Inno Setup). Regresiones en
`tests/test_uso_real_2026_10_08.py` y en las suites afectadas. Manual de uso:
[`Manual_de_uso_Knowledge_Orchestrator.pdf`](Manual_de_uso_Knowledge_Orchestrator.pdf) (fuente en `docs/manual/`; se regenera con `python docs/manual/build_pdf.py`).

| Encontrado usando la app | Corrección |
|---|---|
| «Revisar carpetas» (aviso de Inicio) no hacía nada: navegaba a una página inexistente | Lleva a Ajustes |
| Un fichero roto en la bandeja desaparecía a cuarentena sin rastro en Documentos | Incidencia «Formato no válido/Sin transcripción», no reintentable, con «Abrir ubicación» y «Cerrar incidencia» |
| Tras conectar, Ajustes solo ofrecía «Automático»: `/models` superaba 10 s, no se reintentaba en 5 min y se anunciaba como Broker caído | Límite propio de 30 s, reintento a 30 s, evento propio; la barra lateral se recupera tras cualquier fallo suelto |
| El refresco de 2 s re-seleccionaba cada lista y recargaba sus formularios: en Organización se perdía lo escrito | `_keep_selection`: solo se fija la selección si cambia |
| `TASK_TIMEOUT` a 600 s con el perfil de fábrica (consenso de 4 modelos 27–33B) en un documento de 690 bytes | Plazo 1800 s (migración 025), texto claro y mensaje del Broker en detalles técnicos; evento en la línea de tiempo |
| «Reintentar» fallaba al instante con `DOCUMENT_BUDGET_EXHAUSTED` (el fallo sin coste retenía toda la reserva) | Peticiones `local_only` no reservan dinero |
| Tras «Reintentar», la captura quedaba en PENDING para siempre: ni borrador visible ni «Finalizado» | Pasa a SUBMITTING; migración 026 repara los atascados (excluye reprocesados) |
| 3 de 11 comparaciones fallaban por omitir `replacement_text` y eso apartaba 14 días al mejor modelo (granite) | Si se omite se usa la evidencia literal (la que se aplicaría igualmente); un texto inventado sigue rechazándose |
| Aplicar un cambio sin puente de Obsidian quedaba «aplicándose» para siempre y el lote en recuperación, sin aviso | Lote no aplicable con motivo; «Aplicar cambio» desactivado y explicado; APPLYING visible en Revisión |
| Otros: reimportar no avisaba; `.txt` titulado con el nombre del fichero; propuestas en conflicto editables con error técnico; «UNKNOWN», códigos y eventos sin traducir; columnas cortadas; error en inglés en Fuentes; clic en «Iniciar API» perdido durante el refresco; resultado de «Probar acceso local» borrado a los 2 s; mensaje de contradicciones sin decir cuáles | Corregidos |

Medido contra el Broker real: con «Automático según la tarea» un documento corto tarda 7–14 min; con
«Respuesta directa» + `gemma4:12b`, ~3 min. Comparaciones de prueba: `granite4.1:30b` y
`qwen3-coder:30b` 5/5, `lfm2:24b` 2/5 (responde «Confirma» casi siempre; un prompt con definiciones
no lo arregló y se descartó). **Complemento de Obsidian verificado** con su código sin modificar ejecutado en Node (anfitrión que imita solo `vault.read/process`, `secretStorage` y `onLayoutReady`): desde la ventana real se guardó y comprobó la conexión, se aplicó una contradicción real por lote (escritura y recibo del complemento) y se revirtió (nota restaurada, segundo recibo). Después, **dentro de Obsidian 1.12.7 real** (perfil aislado con `--user-data-dir`, manejado por CDP: modo restringido desactivado, secreto en su llavero, complemento activado): comprobar conexión, aplicar una propuesta real por lote y revertirla desde la ventana del Orchestrator, con 0 fallos; Obsidian ve las notas restauradas y sus recibos APPLIED. La configuración real de Obsidian del usuario no se tocó. También en Obsidian real: una edición hecha dentro de Obsidian después de calcular el cambio hace que el complemento lo rechace y conserva la edición; calculado sobre la versión actual, se aplica. Con el ejecutable final: `--backup`, `--full-backup`, `--restore` (sin `--root`, sobre carpeta no vacía y válido), `--diagnostics` (sin secretos), `--once` (cuarentena visible) y API (lectura, 401 sin credencial o falsa, 403 por permiso, 202/idempotencia/409/400 en ingesta, consumidor de la app y su revocación en caliente): 25/25. «Automático» elige `granite4.1:30b` como modelo de análisis con el catálogo real.

Última tanda (9-oct): **descartar una contradicción dejaba sus afirmaciones «en disputa» para siempre** (fuera del conocimiento vigente, de las consultas y de las políticas, sin forma de recuperarlas desde la ventana): ahora vuelven a su estado anterior si ninguna otra contradicción abierta las implica; la migración 027 repara las que ya estaban así. **Respaldo de afirmaciones en fuentes cortas (1–3 tramos)**: la ponderación por rareza no es medible y castigaba paráfrasis fieles; medido sobre 100 afirmaciones reales, 46→59 respaldadas, sin cambio en transcripciones largas. Verificado de punta a punta en la ventana real: fuente web con dirección local rechazada («Dirección no pública»), edición y desactivación de fuentes, temas inactivos y prioridades, perfil de fábrica «Automático» (≈5 min por documento), novedad detectada e incorporada sola, y **política de autoaprobación que aplicó un cambio sola a través de Obsidian real** 5 s después de reanudar el control global. 594 pruebas + 14 del complemento; ejecutable con 27 migraciones. Después: dos vídeos reales largos de la bandeja (53 tramos) procesados con el Broker: en fuentes largas la regla de respaldo actual coincide con la anterior en 50/50 afirmaciones (la variante sin límite habría cambiado 32: por eso se limitó a ≤3 tramos). API con el ejecutable: pregunta fundamentada con el Broker real (respuesta con citas de afirmaciones vigentes; una consulta hecha antes de cambiar el conocimiento queda STALE con KNOWLEDGE_CHANGED, como documenta el contrato), rechazo de propuesta, cambio de vigencia, alta y comprobación de fuente RSS real (50 novedades), rutas de gobernanza y 403 por permisos. Aprobar por API con Obsidian cerrado: 503 OBSIDIAN_UNAVAILABLE con la operación pendiente (APPLYING, nota intacta); al abrir Obsidian real y recuperar, la propuesta queda APPLIED y la nota con el cambio. Las 13 afirmaciones respaldadas de los vídeos largos revisadas a mano: correctas. Revisadas a mano las 37 «enlazadas por el modelo»: ~12 falsos negativos (paráfrasis; cifras habladas como «015» por 0,15 %), ~24 no comprobables (definiciones, metodología, conclusiones) y 1 que contradice la fuente («alfa negativo» cuando el vídeo dice que aporta valor), bien rechazada. En fuentes largas: precisión 13/13 y cobertura ~50 %. No se amplía la cobertura: normalizar cifras habladas o relajar la ponderación arriesgaría respaldar cifras falsas, que es lo que el criterio protege. 594 pruebas en verde sobre el código final.

Encontrado al verificarlo: un 409 del Broker (identidad ya usada con otro contenido, típico al reprocesar tras reinstalar) se mostraba como «CONTRACT_VALIDATION_FAILED · Broker HTTP 409»; ahora es `IDEMPOTENCY_CONFLICT` con explicación y «Reintentar» lo resuelve. Y granite devolvía como texto propuesto un fragmento literal de la evidencia, que se rechazaba como inferencia: ahora se acepta (se aplica la evidencia completa); un texto inventado se sigue rechazando. 591 pruebas + 14 del complemento.

Cierre (9-oct): granite a veces copia la evidencia perdiendo letras («la versión» → «l sión»), y la
comparación se rechazaba. Ahora se acepta un texto casi literal (parecido ≥ 0,9) siempre que no añada
cifras ni negaciones que no estén en la evidencia; se aplica la evidencia completa. Tras el cambio, en la
ventana real, los 6 análisis con incidencia reintentados terminan y dejan 5 propuestas pendientes de
revisión. Recorridos finales sin fallos: tarjetas de Inicio, envío múltiple, editor de instrucciones,
«Elegir…» de carpetas, filtros y paginación de la Biblioteca, localizar nota movida y retirar, «Revisar
selección/todas», desplegable de lotes anteriores, «Consultar» y «Actualizar recibo» de una reversión
(APPLIED), paginación de Actividad y políticas (evaluar, simular una propuesta, quitar filtro, recargar,
guardar con motivo —revoca la autorización— y simular la página siguiente). **594 pruebas, Ruff y mypy
limpios; ejecutable 0.4.1 regenerado** y comprobado (`--once --root` sobre carpeta nueva: 27 migraciones).


Incremento 29, **3 de octubre de 2026 — System 1 opcional vía AI Broker 2.11**. Reranking de
claims posterior al retrieval y preparación semántica de transcripciones de YouTube en el worker,
con fuente íntegra, mínimos de evidencia y fallback al flujo anterior. El Client_API actualizado
exige `threshold_profile: "default"` para los casos propios; ambos usos lo envían. Los intentos
brutos sirven para diagnóstico y no activan descartes. `target` se admite en evaluación explícita.

**555 pruebas pasan, 16 omitidas por entorno; Ruff y mypy (161 archivos) pasan.** La comprobación
final del contrato/integración incluye 69 pruebas y 23 subtests, sin fallos. Las demos controladas
reducen RAG 12→2 candidatos y resumen 5→3 segmentos; no se afirma calidad ni ahorro de modelos reales.
Por defecto los flags están apagados. [Activación y arquitectura](System1_Integration.md) ·
[Verificación y límites](System1_Acceptance_20261003.md).


Incremento 28, **27–28 de septiembre de 2026 — 0.4.0, la auditoría del 27-sep y el primer conocimiento
real**. Se revisó `docs/Auditoria 20260927/INFORME_AUDITORIA_KNOWLEDGE_ORCHESTRATOR.md`: sus nueve P1 son
ciertos y se reprodujeron (el documento de «verificación» fechado el 4-oct no es fiable: cita un
`probe-results.json` inexistente). Las regresiones de cada hallazgo están en `tests/test_audit_2026_09_27.py`.

| Hallazgo | Qué cambia |
|---|---|
| H01 revisión humana | La política se congela al planificar; el resultado queda como borrador «Pendiente de revisión», se lee en un diálogo y se aprueba ligado al hash del texto o se descarta (fuente y resultado se conservan; «Volver a procesar»). |
| H02 cancelar | Cancela el documento entero: nada READY sale, lo remoto pasa a CANCEL_REQUESTED, workflow y captura quedan CANCELLED (no ERROR) y lo que llegue tarde no lo reabre. |
| H03/H04 aislamiento | Arranque, publicación, análisis y consultas se aíslan por elemento y por etapa; tipos inesperados en el JSON son fallo de contrato del trabajo, no un `TypeError` que bloquea la cola. |
| H05 reintento de análisis | Intentos con identidad propia (`_a2`, `_a3`…), botón «Reintentar análisis» en Actividad con el modelo que se usará. |
| H06 contexto | Salida acotada igual al planificar y al sintetizar; síntesis jerárquica por niveles; ventana = mínimo entre la configurada y la del modelo. |
| H07 evidencia | Extracción por segmentos (el modelo elige N#/S#, no copia texto) y respaldo comprobado contra la captura original: `SOURCE`, `MODEL_LINKED`, `SUMMARY_ONLY`. Solo `SOURCE` propone cambios. |
| H08 presupuesto | Bolsa por documento con reserva al enviar y liquidación con el coste real; lo no ejecutado se devuelve. |
| H09 primera ejecución | Valores por defecto locales, Broker por defecto 127.0.0.1, arranque recuperable si la carpeta guardada falla. |
| H10–H12 | Política de análisis explícita (modelo fijado = exacto, con su proveedor), vetos que caducan y se rehabilitan en Ajustes, fallback de `auto`, reintento que rehace la política entera. |
| H13–H21 | Validación de carpetas, ediciones de Obsidian resolubles desde la Biblioteca, gestión de temas, importación de Markdown normal, Biblioteca paginada, reconciliación incremental, consumidores de API desde la UI, embeddings nativos, opciones sin efecto retiradas. |
| H23 | `--full-backup` y `--restore <zip> --root <vacía>` con manifiesto y hashes. |

**Encontrado al usarla con la configuración real del usuario** (base copiada, nunca modificada):
- La bóveda en Google Drive no admite enlaces duros: las publicaciones se quedaban en PUBLISHING (tres
  notas reales). Ahora se instala con el renombrado no destructivo de Windows.
- SQLite en la carpeta sincronizada registraba «disk I/O error»: aviso en Inicio y al guardar carpetas.
- La bandeja en C: y los datos en Y: rompían las cuarentenas (`os.replace` entre unidades): movimiento
  verificado entre volúmenes; las intenciones huérfanas se apartan una vez en vez de fallar en cada arranque.
- El Broker toma por petición de imagen cualquier prompt que contenga «generar imágenes», aunque esté en
  los datos (4 documentos reales perdidos): `services/broker_shield.py` lo neutraliza con U+2060 y lo
  retira de las respuestas. Es un falso positivo del Broker que conviene corregir allí.

**Validación contra el Broker real (27–28 sep):** cuatro vídeos del usuario publicados (≈3 min cada uno con
`gemma4:12b`); extracción con `lfm2:24b` que por primera vez deja conocimiento: ETFs 17 afirmaciones (8
respaldadas por la fuente), Claude 10 (3 respaldadas, 15 identificadores inventados descartados), vídeo en
inglés 73 (casi todas `MODEL_LINKED`/`SUMMARY_ONLY`, como corresponde a una fuente en otro idioma). Sin
acotar la salida el modelo enumeraba todas las frases y agotaba los 6000 tokens: ahora 25 por nota.

**540 pruebas, cero fallos; Ruff y mypy (158 archivos) limpios.**

Incremento 27, **13 de septiembre de 2026 — 0.3.3, quién cuenta los caracteres**. La extracción de
afirmaciones no había producido nunca una sola afirmación. La causa no era el modelo: **ningún LLM
puede calcular offsets de caracteres**, porque ve tokens, no índices, y el contrato exigía
`document[span_start:span_end] == quote`. El guardián rechazaba, con razón, todo lo que llegaba.

Comprobado con sondas directas al Broker real sobre el mismo documento:

| Modelo | Tiempo | Resultado |
|---|---|---|
| `lfm2:24b` (23.8B) | 20 s | 3 afirmaciones correctas, `quote` == `statement`, **spans inventados** |
| `nemotron:latest` (70.6B) | 131 s | 3 afirmaciones correctas, **spans inventados** |
| `ornith-1.5:35b` (35.5B) | 120 s | 14 646 caracteres de razonamiento y `done_reason=length` |
| `granite4.1:30b` (28.9B) | — | bucle degenerado repitiendo la misma frase |

Los spans inventados eran (0,79), (80,119), (120,169): tramos consecutivos sin relación con el
texto. Además la cita llega con los renglones unidos por un espacio donde el documento tiene un
salto de línea, así que tampoco aparece literalmente.

**Localizar la cita pasa a ser trabajo de la aplicación**, que sí sabe contar (`locate_quote` en
`semantic_maintenance/analisis.py`): coincidencia exacta y, si falla, con espacios normalizados.
Los offsets del modelo se respetan **solo si resultan ciertos** —hacen falta para distinguir dos
ocurrencias idénticas de la misma cita, que es lo que comprueba `test_maintenance_reversion`— y
`span_start`/`span_end` dejan de ser obligatorios en el esquema. La garantía anti-invención no se
relaja: cita no localizable, rechazo. La evidencia que se guarda es `document[start:end]`, no la
versión del modelo, porque parches, deriva y procedencia comparan contra el texto del documento.

**Ajustes, revisada como interfaz (13-sep-2026).** La pantalla había crecido con la 0.3.1–0.3.3 y
se analizó sobre capturas reales: el editor de perfiles —lo único que se cambia con frecuencia—
empezaba a unos 800 px de desplazamiento, debajo de carpetas, Broker y Obsidian, que se tocan una
vez. Ahora la política del perfil va primero y la infraestructura debajo. Los dos selectores se
llaman por lo que hacen —**«Modelo que redacta el apunte»** y **«Modelo que extrae afirmaciones»**,
antes «Modelo» y «Modelo para análisis», indistinguibles— con una línea que explica por qué el
segundo debe devolver una estructura exacta. Además: el formulario deja de ir apretado contra el
borde (la lista de perfiles ya no se reparte la mitad de la pantalla), el párrafo de ayuda dejó de
salir cortado por la izquierda, las columnas de la lista ya no truncan a media palabra, las rutas
largas se muestran por su final —que es lo que distingue `…\inbox` de `…\vault`— y los dos botones
«Guardar conexión» idénticos pasan a ser **«…al Broker»** y **«…con Obsidian»**.

**Control y memoria, a petición del usuario:**
- **«Modelo para análisis»** propio en Ajustes (`profiles.analysis_model`, migración 022): redactar
  prosa y devolver JSON conforme a esquema son trabajos distintos, y un modelo bueno en el primero
  puede ser inservible en el segundo. Vacío = lo elige la aplicación. Manda sobre la elección
  automática, tanto en extracción y comparación como en las consultas fundamentadas.
- **`analysis_model_failures`**: el modelo que rompe una tarea con esquema queda apuntado y la
  elección automática deja de proponerlo. Elegirlo a mano sigue siendo posible.

**490 pruebas en 210,983 s, cero fallos**; Ruff y mypy de 151 archivos pasan. Ejecutable 0.3.3
regenerado (arranca y se mantiene; sin instalador porque falta Inno Setup 6). **Recorrido de
usuario repetido íntegro sobre 0.3.3 con la ventana real: 26 correctos, 1 no ejecutado (U22, exige
el Broker real), cero errores** —igual que el baseline de 0.3.0, así que la interfaz no se degradó
entre 0.3.1 y 0.3.3—, más **5 pasos nuevos** que ejercitan el selector de análisis y la memoria de
fallos desde la propia pantalla de Ajustes.

**Validación en vivo, con el token administrativo renovado (13-sep-2026).** El circuito completo
funciona: Broker detectado en 1,1 s, 88 modelos descubiertos, modelos de redacción y de análisis
elegidos desde Ajustes, nota de 6989 caracteres publicada. **La extracción todavía no deja
afirmaciones**, y la causa ya no es la aplicación sino el modelo. Tres obstáculos encadenados:

1. *Offsets imposibles* — corregido en este incremento (`locate_quote`).
2. *`TASK_TIMEOUT` a los 600 s* — corregido: las peticiones semánticas fijaban
   `execution.timeout_seconds: 600` y el Broker cortaba la tarea mientras un modelo de 28.9B seguía
   generando. Ahora 1800 s; el contrato solo exige entero positivo. Son tareas de fondo: que tarden
   no molesta, que se corten sí.
3. *El modelo parafrasea en vez de copiar* — **abierto**. `lfm2:24b` devuelve 10 afirmaciones
   correctas en contenido y **ninguna cita literal**; `granite4.1:30b` da 3 de 4 aceptables en sonda
   directa pero una sola frase inventada dentro del circuito real. El guardián las rechaza con razón:
   admitir texto reescrito por el modelo haría el conocimiento no verificable contra la nota.

Queda por decidir si se abre el filtro de proveedor —`JSON_TASK_PROVIDERS = ("ollama",)` deja pasar
**3 modelos de 150**, ignorando 70 en línea y utilizables de LM Studio y NVIDIA— o si la evidencia se
ancla a la frase real del documento de la que procede cada afirmación. También conviene que un veto
de `analysis_model_failures` pueda olvidarse cuando la causa del fallo se corrige: `granite4.1:30b`
habría quedado excluido para siempre por fallos ajenos a él.

**Antecedente, ya resuelto: la credencial del Broker.** El worker exige `health()` **y**
`auth_check()`; `GET /api/v1/auth/check` responde **403 `ADMIN_AUTH_REQUIRED`** con el token admin,
con `Authorization: Bearer` y sin cabecera, mientras `/health`, `/api/v1/capabilities` y
`/api/v1/models` responden 200 (incluso sin credencial). Con ese 403 la aplicación queda «sin
Broker» y no hay publicación ni extracción. El día anterior el mismo recorrido pasaba en 2,1 s:
el token admin rotó al reiniciarse el Broker, algo que el propio cliente ya documenta. Reproducido
con el árbol limpio en 0.3.2, así que no lo causa ningún cambio de este incremento. Detalle en
`User_Workflow_QA_2026-09-11.md`.

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
