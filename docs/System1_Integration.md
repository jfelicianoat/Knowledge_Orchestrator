# System 1 en Knowledge Orchestrator

## Arquitectura encontrada y plan

Las consultas durables (`KnowledgeQueryService` / `KnowledgeQueryProcessor`) recuperan claims con citas exactas, vigencia y huella de conocimiento. La recuperación actual es FTS/BM25; `KnowledgeAccess.semantic_search` ofrece además coseno sobre embeddings del modelo declarado. Se reutilizan ambas rutas, con un vector opcional en `/query`, y se aplica el reranker tras la recuperación y las restricciones de evidencia/tamaño, antes del selector generativo existente.

Las capturas se conservan completas en SQLite y disco. `WorkflowPlanner` usa `TextChunker` para preparar tareas single/map y una síntesis. El prefiltrado se ejecuta en el worker asíncrono antes de planificar capturas nuevas, sobre segmentos del chunker, con offsets y huella de la fuente. La recuperación de arranque deja esta preparación al worker cuando está habilitada. No se modifica YT_Capture_Plugin.

`BrokerClient` consume el contrato 2.11: capacidad `system1_judgments`, POST síncrono autenticado y timeout independiente. Se comprueban `accepted`, el tipo y dominio de `decision` y la confianza. `score` es un índice ordinal, no la confianza. El Broker controla proveedores; prevalece el nuevo `Client_API.md` sobre el orden de proveedores del prompt antiguo. Los juicios de KO mantienen `cloud_allowed: false`.

La configuración permite habilitar cada uso, modo sombra, umbrales y presupuestos. Los fallos recuperan la entrada/ranking anterior. La auditoría reutiliza snapshots, planes y eventos existentes; no necesita otra base de datos. Las pruebas y demos usarán respuestas controladas y distinguirán tokens estimados de consumo real.


## Cambios del Client_API.md revisados el 3 de octubre de 2026

| Cambio del contrato 2.11 | Efecto en KO |
|---|---|
| Caso propio sin perfil conocido: `UNKNOWN_USE_CASE` | Los dos casos envían instrucciones y `threshold_profile: "default"`. Se puede configurar un perfil acordado con el operador por cada uso. |
| `target` fija un juez para evaluación | El cliente valida y transmite ese campo en llamadas explícitas. El RAG y el filtrado no lo envían: el Broker conserva su política de proveedores. |
| `attempts` incluye notas brutas y `score_source` | Se conservan en el diagnóstico sin usarlas para seleccionar o descartar. Solo se aplica el juicio de primer nivel con `accepted: true`. |
| System 2 devuelve `SELF_REPORTED_SCORE` | Se conserva el contexto original. También se rechaza una respuesta incoherente que marque como aceptada una nota `self_reported`. |
| Baja confianza/margen no pide otra opinión | KO tampoco reintenta el juicio ni invoca otro proveedor; restaura la entrada anterior. |
| `INPUT_TOO_LARGE` | Fallback completo. No se obtiene una decisión a partir de texto recortado. |
| `describe_images` resuelve la ingesta de figuras | Sin cambio en KO: esta aplicación envía texto inline y no sube documentos a `/files`. |

## Activación y configuración

Por defecto ambos usos están apagados, de modo que una instalación existente mantiene su comportamiento. Copiar `docs/system1.example.json` a `state/system1.json` de la carpeta de datos activa ambos en modo sombra. Reiniciar KO para cargarlo. En sombra se registran las propuestas pero se envía el contenido completo. Cambiar `shadow_mode` a `false` para aplicar las selecciones. La conexión y el token siguen siendo los configurados en Ajustes del Broker.

También puede configurarse por entorno antes de arrancar (todas las claves admiten el prefijo `KO_SYSTEM1_` y su nombre en mayúsculas):

```powershell
$env:KO_SYSTEM1_RAG_ENABLED = "true"
$env:KO_SYSTEM1_TRANSCRIPT_ENABLED = "true"
$env:KO_SYSTEM1_SHADOW_MODE = "false"
.\start_orchestrator.bat
```

Las variables de entorno prevalecen sobre el fichero. `rag_threshold_profile` y `transcript_threshold_profile` valen `default`; un perfil propio debe existir en el Broker. La configuración local no cambia los umbrales de aceptación del Broker, solo añade las restricciones de KO.

| Parámetro | Default | Uso |
|---|---:|---|
| `relevance_keep` / `relevance_uncertain` | 0.80 / 0.55 | Nivel de utilidad normalizado de la rúbrica ordinal de 11 niveles. No es probabilidad de acierto. |
| `rag_min_confidence` | 0.85 | Confianza mínima en el nivel ordinal. Si no se cumple, fallback completo. |
| `min_chunks` / `max_chunks` | 2 / 8 | Mínimo de evidencia y límite de candidatos seleccionados. |
| `context_tokens` | 6000 | Presupuesto estimado del JSON de candidatos enviado al selector. |
| `transcript_min_confidence` | 0.90 | Solo descarta filler/promotion por encima de este valor; lo ambiguo se conserva. |
| `segment_tokens` / `max_segments` | 600 / 64 | Tamaño estimado de segmento y máximo de segmentos juzgados. |
| `adjacent_segments` | 1 | Contexto de un claim para investigación. |
| `http_timeout_seconds` / `stage_timeout_seconds` | 75 / 90 | Timeout de la petición y plazo máximo total de cada preparación. |
| `require_calibrated` | false | Si es true, los scores actuales sin calibrar producen fallback. |

Los juicios se hacen secuencialmente: el contrato no ofrece batch. El timeout total, los límites de segmentos o una caída del Broker conservan el contexto original. Si `min_chunks` no cabe en el presupuesto reducido, se vuelve al contexto del retrieval anterior, que conserva su límite previo de 24 candidatos / 60.000 caracteres. No se destruye evidencia para cumplir un presupuesto imposible.

## Flujo y trazabilidad

`POST /api/v1/query` admite opcionalmente `retrieval: {"vector": [1, 0], "model": "espacio-de-embeddings"}`. El vector y los embeddings almacenados deben pertenecer al mismo modelo. Sin ese objeto, la búsqueda sigue siendo FTS/BM25. `/search/semantic` conserva su contrato y devuelve el ranking vectorial original; el reranker se aplica en la consulta generativa posterior.

El snapshot de la consulta guarda la pregunta, el tipo de retrieval, la selección y la auditoría. Se persiste antes de enviar al generador, con una clave idempotente correspondiente al contenido final. Los reintentos y la recuperación reutilizan ese cuerpo. Si cambia la evidencia durante el juicio, la consulta pasa a STALE y no se envía. La respuesta sigue construyéndose con citas verificadas, sin texto factual inventado.

Para capturas nuevas de YouTube, el worker prepara la transcripción en modo `research`, conservando claims y contexto adyacente. El chunker existente determina segmentos contiguos; el texto seleccionado son cortes exactos de la fuente, con timestamps incluidos. El plan del workflow guarda su hash, offsets, categoría, confianza y motivo. La captura fuente en disco/SQLite no se modifica. El servicio también permite `purpose="summary"`, mostrado en la demo. Los documentos generales y los reprocesados que se planifiquen expresamente por la vía síncrona conservan el flujo anterior.

La auditoría guarda proveedores/modelos reales devueltos por el Broker, las notas y metadatos de intentos; no añade los prompts ni el contenido de los segmentos a eventos. Los juicios son independientes de las tareas generativas y siempre usan `cloud_allowed: false`. Detener la app cancela la preparación en espera, y el siguiente arranque recupera las consultas reclamadas que no llegaron a enviarse.

## Demostraciones reproducibles

Desde la carpeta del proyecto:

```powershell
.\.venv\Scripts\python.exe scripts/demo_system1.py --output ../output/System1_Demo_20261003.json
```

`../output/System1_Demo_20261003.json` contiene 12 candidatos, sus puntuaciones y los 2 conservados; además, una transcripción de 5 segmentos con los 3 conservados para resumen y los 4 conservados para investigación, cada uno con motivo y offsets. Incluye dos escenarios de Broker caído que restauran los originales.

La demo usa juicios controlados: **no prueba la calidad semántica de Nimble/Laya ni calibra sus probabilidades**. Sus conteos de tokens usan la estimación existente `ceil(caracteres/4)`. Las ratios de fallback tienen como denominador los escenarios de la demo; no son tasas de producción. Los checks de recall/precision comparan la selección con las etiquetas de ese fixture; hacen visible la política, no una evaluación del modelo real. No se afirma ahorro neto de inferencia: faltan consumo y latencias reales, incluido el coste de los juicios.

## Verificación

Las regresiones específicas están en `tests/test_system1.py` y `tests/test_system1_integration.py`: evidencia exacta con menor similitud, mínimo con todos los scores bajos, presupuesto, incertidumbre, Broker caído, contratos de aceptación, default/perfiles propios, `target`, nota autodeclarada, fuente íntegra, contexto adyacente, modo sombra, recuperación e interrupción.

Los resultados finales de la batería completa y los conteos de la demo se registran en el informe de aceptación al terminar la verificación.
