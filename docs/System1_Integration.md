# System 1 en Knowledge Orchestrator

## Arquitectura encontrada y plan

Las consultas durables (`KnowledgeQueryService` / `KnowledgeQueryProcessor`) recuperan claims con citas exactas, vigencia y huella de conocimiento. La recuperación actual es FTS/BM25; `KnowledgeAccess.semantic_search` ofrece además coseno sobre embeddings del modelo declarado. Se reutilizan ambas rutas, con un vector opcional en `/query`, y se aplica el reranker tras la recuperación y las restricciones de evidencia/tamaño, antes del selector generativo existente.

Las capturas se conservan completas en SQLite y disco. `WorkflowPlanner` usa `TextChunker` para preparar tareas single/map y una síntesis. El prefiltrado se ejecuta en el worker asíncrono antes de planificar capturas nuevas, sobre segmentos del chunker, con offsets y huella de la fuente. La recuperación de arranque deja esta preparación al worker cuando está habilitada. No se modifica YT_Capture_Plugin.

`BrokerClient` consumirá el contrato 2.11: capacidad `system1_judgments`, POST síncrono autenticado y timeout independiente. Se comprueban `accepted`, el tipo y dominio de `decision` y la confianza. `score` es un índice ordinal, no la confianza. El Broker controla proveedores; prevalece el nuevo `Client_API.md` sobre el orden de proveedores del prompt antiguo. Los juicios de KO mantienen `cloud_allowed: false`.

La configuración permite habilitar cada uso, modo sombra, umbrales y presupuestos. Los fallos recuperan la entrada/ranking anterior. La auditoría reutiliza snapshots, planes y eventos existentes; no necesita otra base de datos. Las pruebas y demos usarán respuestas controladas y distinguirán tokens estimados de consumo real.
