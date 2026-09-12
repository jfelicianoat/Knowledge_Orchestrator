# Prueba de uso de Knowledge Orchestrator

Solicitud: probar toda la aplicación como usuario. Primera sesión (11-sep-2026): bloqueada
porque Computer Use no tenía acceso a la ventana de Python. Segunda sesión (11-sep-2026,
interfaz **0.3.0**): recorrido ejecutado con la ventana real.

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
