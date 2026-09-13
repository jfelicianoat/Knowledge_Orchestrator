# Prueba de uso de Knowledge Orchestrator

Solicitud: probar toda la aplicación como usuario. Primera sesión (11-sep-2026): bloqueada
porque Computer Use no tenía acceso a la ventana de Python. Segunda sesión (11-sep-2026,
interfaz **0.3.0**): recorrido ejecutado con la ventana real.

## Sesión del 13-sep-2026 (0.3.3): recorrido completo repetido sobre la versión nueva

El recorrido de 27 pasos se volvió a ejecutar íntegro con la ventana real sobre **0.3.3**, porque
el de la tabla de abajo probó la 0.3.0 y desde entonces la aplicación cambió (fila nueva en
Ajustes, carga de perfiles, elección de modelo). Resultado: **26 correctos, 1 no ejecutado (U22,
que exige el Broker real), cero errores** — mismo resultado que el baseline de 0.3.0, así que nada
de 0.3.1 → 0.3.3 estropeó la interfaz. U24 confirma las 8 acciones principales enteras dentro de
1080×680 y U20 que al reabrir se recuperan las 4 notas y los 6 documentos sin duplicar.

Y como el recorrido general no tocaba el control entregado en 0.3.3, se añadió uno propio
(`ko_flow_analysis_model.py`), también por la interfaz: **5 pasos, todos correctos**.

**Ajustes, revisada como interfaz y aprobada por el usuario.** Sobre capturas reales se vio que el
editor de perfiles —lo único que se cambia a menudo— empezaba a unos 800 px de desplazamiento,
debajo de carpetas, Broker y Obsidian. Se subió la política del perfil y se bajó la infraestructura;
los selectores pasaron a llamarse «Modelo que redacta el apunte» y «Modelo que extrae afirmaciones»
(antes «Modelo» y «Modelo para análisis», indistinguibles) con una línea que explica por qué el
segundo debe devolver una estructura exacta. El usuario respondió «sí, pero sigue mejorando», y en
esa segunda tanda se corrigieron las dos cosas que había dejado fuera: las rutas largas muestran
debajo la misma ruta acortada por el centro —lo que distingue `…\inbox` de `…\vault`— conservando
el campo editable, y los dos botones «Guardar conexión» idénticos pasaron a «…al Broker» y «…con
Obsidian». Tres defectos propios salieron por el camino y se arreglaron antes de enseñar nada: el
formulario apretado con media pantalla vacía, el párrafo de ayuda cortado por la izquierda y las
columnas de la lista truncadas a media palabra.

Tras cada tanda se repitió el recorrido completo: **26 correctos, 1 no ejecutado, cero errores** en
las cuatro ejecuciones, la última sobre el código definitivo. Nota de método: el arnés buscaba
«Guardar conexión» por coincidencia parcial y, con dos botones que contenían esa cadena, podía
invocar el equivocado y dar un falso verde; el paso U08c se precisó a «Guardar conexión al Broker».

| ID | Recorrido | Resultado observado | Estado |
|---|---|---|---|
| A01 | Ajustes ofrece «Modelo para análisis» | 5 opciones, valor inicial «Automático (Broker)»; no se ofrece lo que razona ni lo especializado | Correcto |
| A02 | Elegir `lfm2:24b` y guardar | Se guarda en el perfil; pie «La política se aplicará a documentos nuevos.» | Correcto |
| A03 | La elección manda sobre la automática | La petición con esquema llevaría `lfm2:24b` | Correcto |
| A04 | Sobrevive al refresco automático | El desplegable sigue mostrando lo guardado | Correcto |
| A05 | Memoria de fallos | Tras un `SEMANTIC_CONTRACT_FAILED`, la elección automática pasa de `lfm2:24b` a `llama-instruct`; lo fijado a mano se respeta igual | Correcto |

## Sesión del 13-sep-2026 (0.3.3): por qué la extracción no producía afirmaciones

Se probaron cuatro modelos del catálogo del usuario contra el Broker real, con el prompt y el
esquema de extracción de la aplicación, sobre el mismo documento:

| Modelo | Tiempo | Resultado |
|---|---|---|
| `lfm2:24b` | 20 s | 3 afirmaciones correctas y literales · **spans inventados** |
| `nemotron:latest` | 131 s | 3 afirmaciones correctas · **spans inventados** |
| `ornith-1.5:35b` | 120 s | `INVALID_PROVIDER_RESPONSE`: 14 646 caracteres razonando, `done_reason=length` |
| `granite4.1:30b` | — | JSON válido con texto degenerado en bucle; el guardián de spans lo rechazó |

Conclusión: el problema no era la calidad del modelo sino el contrato. Se pedía
`document[span_start:span_end] == quote`, es decir, **contar caracteres**, que es justo lo que un
LLM no puede hacer. Los spans devueltos fueron (0,79), (80,119), (120,169) — consecutivos y sin
relación con el texto — y la cita llegó con los saltos de línea convertidos en espacios. Corregido
en 0.3.3: la cita la localiza la aplicación; el rechazo se mantiene si no aparece en el documento.

**Recorrido en vivo con el token renovado: B01–B03 correctos, B04 abierto.** Con la credencial
válida el circuito entero responde —Broker en 1,1 s, 88 modelos, modelos de redacción y análisis
elegidos desde Ajustes, nota de 6989 caracteres publicada— y la extracción llega a ejecutarse. No
produce afirmaciones porque los modelos disponibles no copian citas literales:

| Modelo | Resultado sobre la nota real (808 caracteres) |
|---|---|
| `lfm2:24b` | 10 afirmaciones correctas en contenido · **0 citas literales** · todas rechazadas |
| `granite4.1:30b` | sonda directa: 4 afirmaciones, 3 aceptables · circuito real: 1 frase inventada |
| `nemotron:latest` | 1 afirmación de relleno sobre el propio esquema |
| `ornith-1.5:35b` | 14 646 caracteres razonando, `done_reason=length` |

Por el camino se corrigió un límite propio: las peticiones semánticas fijaban `timeout_seconds: 600`
y el Broker devolvía `TASK_TIMEOUT` mientras el modelo seguía generando; ahora 1800 s. Y se comprobó
que la memoria de fallos funciona en real: registró sola `lfm2:24b · SEMANTIC_CONTRACT_FAILED` tras
las paráfrasis. Queda decidir si se abre el filtro de proveedor —deja pasar 3 modelos de 150— o si la
evidencia se ancla a la frase real del documento de la que procede cada afirmación.

**Antecedente ya resuelto: el Broker rechazaba la credencial.** `GET /api/v1/auth/check`
devuelve `403 ADMIN_AUTH_REQUIRED` con `X-Admin-Token`, con `Authorization: Bearer` y sin cabecera,
mientras `/health`, `/api/v1/capabilities` y `/api/v1/models` responden 200 sin credencial alguna.
`BrokerWorker._check_health` exige que pasen `health()` y `auth_check()`, así que la aplicación
queda «sin Broker»: B01 a B04 fallan por espera agotada (90 s, 120 s, 480 s, 420 s) sin llegar a
publicar. El día anterior el mismo recorrido pasó en 2,1 s, y se reprodujo con el árbol limpio en
0.3.2: el token administrativo rotó al reiniciarse el Broker y hay que renovarlo en el PC IA.
Verificación local completa: **490 pruebas, cero fallos**; Ruff y mypy de 151 archivos.

Dos defectos del propio arnés de prueba, corregidos aquí porque falsearon diagnósticos: las
corridas compartían el sandbox `ko_broker/` y la fase 1 lo borra con `rmtree`, de modo que una
segunda corrida mataba a la primera con `unable to open database file` —lo que parecía un fallo de
la aplicación al detectar el Broker—; y medir si un control «cabe» en Ajustes por coordenadas
absolutas da un falso desbordamiento de 629 px, porque la página se desplaza (`Canvas` +
`TScrollbar`, contenido 1333 px, alcanzable 1333 px).

## Cómo se ejecutó

- Ventana real `OrchestratorDashboard` y runtime real con sus workers (vigilancia de la
  carpeta, fuentes, lotes, automatización), sobre una raíz de datos de ensayo creada para la
  prueba. No se leyó ni modificó la configuración, el token ni la bóveda del usuario.
- `LOCALAPPDATA` apuntaba a la raíz de ensayo: «Guardar carpetas» no toca la configuración real.
- Las acciones son las de la interfaz: clic en la navegación, atajos Ctrl+número, `invoke()` de
  sus botones, selección en las listas, texto en los campos y respuestas a los diálogos modales
  (se contesta «Sí» y se da un motivo cuando la aplicación lo pide).
- **Límites.** El Broker real no participa (URL a un puerto cerrado). Donde el flujo necesita la
  respuesta del modelo, se simula con los helpers de las pruebas y el paso lo declara
  («Broker simulado»). Obsidian se sustituye por el editor de ensayo `FakeNoteEditor`.
  La fuente pública usa la red real de este equipo.
- Script: `ko_user_flows.py` (carpeta de trabajo de la sesión); capturas por paso.

## Resultado final: 26 correctos, 1 no ejecutado

| ID | Recorrido | Resultado observado | Estado |
|---|---|---|---|
| U01 | Abrir y navegar | 10 pantallas por clic; Ctrl+2/4/0/1 llevan a Documentos, Biblioteca, Ajustes, Inicio | Correcto |
| U02 | Broker no disponible | Barra lateral «Broker con incidencia» y aviso con la dirección, conservación de documentos y dónde corregirlo | Correcto tras corrección |
| U03 | Biblioteca | Búsqueda, temas, vista previa verificada por hash, URI `obsidian://`, «Ver documento de origen» | Correcto |
| U04 | Importar | Tres documentos entran; pie «Documento importado: se procesará automáticamente.» | Correcto |
| U05 | Reimportar el mismo | Sin trabajo nuevo; pie explica el duplicado y la cuarentena | Correcto tras corrección |
| U06a | Entrada no válida | Pie explica el formato que falta y la cuarentena | Correcto tras corrección |
| U06b | Archivo bloqueado | Incidencia «Archivo bloqueado» en Necesitan atención; Reintentar lo incorpora al liberarse | Correcto |
| U07 | Filtros y búsqueda | Filtros, búsqueda, vacío explicado, abrir ubicación, detalles técnicos | Correcto |
| U08a | Perfil e instrucciones | Guardar se habilita al editar; perfil e instrucciones persistidos | Correcto |
| U08b | Validación | «La longitud máxima… debe ser un número entero de tokens, por ejemplo 8000.» | Correcto tras corrección |
| U08c | Carpetas, Broker, Obsidian | Carpetas guardadas en ensayo; token protegido y eliminado; Obsidian pide configurar conexión | Correcto |
| U09 | Afirmaciones | Vigentes, búsqueda por entidad y detalle con evidencia y evolución | Correcto |
| U10 | Fuente local | «Dirección no pública» en la lista de fuentes | Correcto |
| U11 | Feed público real | «Al día», 50 novedades; incorporar deja «En flujo documental» | Correcto |
| U12 | Leer propuesta | Ahora 3.13 / Propuesto 3.14; contador en la barra lateral | Correcto |
| U13a | Editar propuesta | Revisión de propuesta 1→2 con justificación propia | Correcto |
| U13b | Aplicar | Vista previa del lote, confirmación, lote COMPLETE, nota actualizada | Correcto |
| U13c | Descartar | Propuesta «Contradice» descartada; nota sin cambios | Correcto |
| U16 | Todas las pendientes | Plan explica 0 de 1 elegibles y 1 excluida | Correcto |
| U17 | Nueva política | Guardar sin fuentes se rechaza con motivo claro (no se admite ámbito global) | Correcto (validación) |
| U18 | Pausar/reanudar | Cambio con confirmación y motivo, en ambos sentidos | Correcto |
| U19 | Reversión | Vista previa, confirmación con motivo, nota vuelve a 3.13 | Correcto |
| U20 | Cerrar y reabrir | Mismas notas y documentos; nada duplicado | Correcto |
| U21 | API local | 200 con credencial, 401 sin ella, actividad registrada, detenida | Correcto |
| U22 | Pregunta al Broker | Requiere el Broker real | **No ejecutado** |
| U24 | Ventana 1080×680 | Reintentar, Aplicar cambio y Abrir en Obsidian visibles | Correcto tras corrección |

U14 (edición humana tras la propuesta), U15 (bloqueo manual) y U23 (fuente adversaria) no se
recorrieron en la interfaz; tienen cobertura en las pruebas automáticas existentes.

## Defectos encontrados y corregidos en la sesión

1. **Estado del Broker nunca actualizado en la interfaz.** El worker solo emite sus eventos de
   salud por el puente, no los guarda en SQLite, y el resumen leía SQLite: el Broker figuraba
   siempre «sin comprobar» y el aviso no aparecía. La vista recoge ahora esos eventos al vuelo.
2. **Revisión inutilizable en ventana pequeña:** a 1080×680 «Aplicar cambio» quedaba fuera de
   la ventana. Las acciones pasan bajo el título.
3. **Mensajes técnicos en el pie:** «Ingestion result: capture_id ya registrado»,
   «$: falta la apertura del frontmatter YAML». Ahora son frases con la causa y qué pasa con el archivo.
4. **Error de validación en inglés** en Ajustes (`invalid literal for int()`).
5. **Frases pegadas** en el panel de reversión («…individual Actualiza…»).
6. Antes del recorrido: Ajustes ensanchaba la ventana a 2560 px; posición `2147483647` visible
   en Organización; aborto `Tcl_AsyncDelete` en la regresión; `build_windows.ps1` no encontraba
   las migraciones.

## Recorrido contra el Broker real (12-sep-2026, 0.3.1)

Broker `192.168.1.52:8765`, contrato 2.10, sobre raíz de ensayo aislada.

| ID | Recorrido | Resultado observado | Estado |
|---|---|---|---|
| B01 | Detectar el Broker | «Broker disponible» en la barra lateral; contrato 2.10, carriles inference/ingestion y métodos ofrecidos en Ajustes | Correcto |
| B02 | Catálogo y elección de modelo | 149 modelos descubiertos, **87 ofrecidos** (se descartan incompatibles y en cuarentena); elegido `gemma4:12b · razona · 262k contexto` con presupuesto de perfil 8000 | Correcto |
| B03 | Documento real de principio a fin | «En cola del Broker → Procesando → Completado»; nota de 6885 caracteres publicada en 122 s | Correcto |
| B04 | Extracción de afirmaciones | La tarea llega al Broker y falla: `SEMANTIC_CONTRACT_FAILED`, «El Broker no devolvió JSON semántico estricto» | **Fallo conocido** |
| B05 | Consulta con y sin evidencia | La API acepta, responde y distingue el caso; ambas contestan «evidencia insuficiente» porque sin B04 no hay claims que citar | Parcial |

**Intentos previos, como contraste.** Con `gemma-4-e4b-it-obliterated` (que el Broker ya marcaba
incompatible) y 1200 tokens: dos intentos de 8 y 15 minutos sin publicar, con
`INVALID_PROVIDER_RESPONSE` y `done_reason=length`. Un tercer intento murió con `HTTP 409`
legítimo: se reutilizó el mismo `capture_id` y el Broker conserva la clave idempotente anterior.

**Lo que esto acredita:** el ciclo documento → Broker → nota publicada funciona de verdad con un
modelo adecuado, y el filtro del catálogo evita la elección que hacía fallar todo.
**Lo que no:** la extracción de claims y, por tanto, la consulta fundamentada **con** evidencia.

## Observaciones sin corregir

- Un archivo rechazado (duplicado o formato no válido) solo se comunica en el pie y en
  «Actividad reciente» («Archivo rechazado»); no aparece en «Necesitan atención». Si el pie
  cambia antes de leerlo, la única pista queda en la actividad.
- Crear una política exige elegir fuentes explícitamente; el formulario no lo indica hasta guardar.
- El recorrido real Plugin → Orchestrator → Broker → Obsidian sigue pendiente (Broker y puente reales).
