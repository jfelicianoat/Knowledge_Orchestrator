# Fase 10 — Knowledge API

Registro de checkpoint: 5 de septiembre de 2026.

## 1. Estado encontrado

Fase 9 verificada con 174 pruebas. No había servidor API ni dependencia de framework web.
La ingesta, el validador de capturas, FTS, embeddings opcionales, cliente Broker, publicación
y recuperación proporcionan los componentes reutilizables. La UI sigue siendo Tkinter.

## 2. Diseño propuesto y aplicado

Adaptador WSGI local bajo `/api/v1`, separado de servicios. Se incorpora un servidor de
loopback con librería estándar; `KnowledgeApi` puede montarse como aplicación WSGI.
No se migra el framework UI ni se cambia ningún contrato Broker existente.
Tokens independientes por consumidor, permisos read/query/ingest y pertenencia de trabajos
por consumidor. Las intenciones y las consultas se guardan antes de producir efectos externos.
Detalles, ejemplos y alcance de despliegue en `Knowledge_API.md`.

## 3. Cambios realizados

- Documentos, revisiones, entidades, claims, evidencia y sucesiones con filtros current/history/all.
- Búsqueda FTS y búsqueda coseno sobre vectores del modelo/dimensión declarados.
- Query durable que usa el Broker para seleccionar evidencia y devuelve citas exactas.
- Insuficiencia explícita, validación de IDs, contexto no confiable y respuesta obsoleta
  cuando cambian datos, estados o consistencia documental durante/después de la consulta.
- Ingestión API idempotente: intención SQLite → entrega al inbox → servicios existentes.
- Rutas de consulta de propuestas existentes; las decisiones ampliadas pertenecen a fases 12–14.
- Autenticación obligatoria, permisos, límites de JSON, errores saneados y auditoría sin credenciales.
- Contrato OpenAPI de rutas, cuerpos, parámetros, permisos y schemas de respuesta.
- Arranque CLI `--api --api-port`, con integración de los trabajos en el worker existente.

## 4. Archivos modificados

Nuevos: paquete `api` (application/auth/contracts/openapi/response_schemas/server),
`repositories/query_repository.py`, servicios `knowledge_access.py`, `knowledge_query.py`,
`api_ingestion.py`, migración 013, `tests/test_phase_ten_knowledge_api.py` y documentación API.
Integración: app, runtime, BrokerWorker, filtro current de KnowledgeRepository y prueba de migraciones.
Los cambios previos de fase 9 se conservan.

## 5. Migraciones

013 añade `knowledge_queries` y `api_ingestions`, con propietario, claves idempotentes,
estado y contenido recuperable. No guarda tokens. No recrea tablas existentes.
La evolución de bases legacy y la inicialización repetida siguen pasando la batería.
No se ejecutó la migración contra los datos reales del usuario.

## 6. Tests añadidos/modificados

Quince pruebas nuevas de contrato y comportamiento: permisos/auditoría, current/history,
documentos y revisiones, espacios vectoriales, validación HTTP, query y propiedad, insuficiencia,
idempotencia/reinicio, prompt injection/IDs inventados, respuestas obsoletas, backoff,
ingesta por el flujo existente, recuperación de entrega, OpenAPI y configuración de credenciales.
La prueba de base de datos espera 13 migraciones.

## 7. Resultado de verificaciones

VERIFICADO con `.venv/Scripts/python.exe` y `PYTHONPATH=src`:

- `python -B -m unittest discover -s tests -q`: **189 pruebas OK**, 30,330 s.
- `python -m ruff check src tests --no-cache`: **All checks passed**.
- `python -m mypy src --no-incremental --cache-dir <temporal>`:
  **Success: no issues found in 96 source files**.
- HTTP real en un puerto temporal de 127.0.0.1: **200** con credencial y **401** sin credencial.
  Se cerraron servidor, hilo y raíz temporal al finalizar.
- `git diff --check`: sin errores; avisos normales LF/CRLF de Windows.

## 8. Riesgos/deuda

NO VERIFICADO: autenticación e inferencia reales contra Broker. Se probó la conexión
configurada `192.168.1.52:8765` con credencial temporal facilitada por el usuario.
Health/auth/capabilities no llegaron a recibir HTTP. El diagnóstico de socket confirmó
`PermissionError`, WinError **10013**, errno **13**. No equivale a rechazo de la credencial.
La credencial no se escribió en código, documentación, SQLite ni logs del programa.

REQUIERE PRUEBA REAL: consulta completa con el Broker y cadena Plugin → Broker → Obsidian.
El servidor incluido es local; un despliegue de red requiere servidor WSGI/TLS y límites
apropiados. Los permisos son por consumidor y bóveda del runtime, no por carpeta.
La búsqueda vectorial recibe un vector del consumidor; no genera embeddings desde texto.
Query tiene recuperación acotada y devuelve citas, no síntesis libre verificada del modelo.
La invalidación de respuestas ante cambios del corpus es conservadora y puede exigir
repetir una pregunta tras un cambio no relacionado.
Monitorización de fuentes, mantenimiento ampliado, UI integral y gobernanza siguen pendientes.

## 9. Estado del checkpoint

Checkpoint local y de contratos superado; prueba externa pendiente por restricción de red
documentada. No se declara completado el objetivo global ni verificada la integración externa.

## 10. Próximo paso

Fase 11: fuentes y conectores extensibles, scheduler durable, deduplicación, backoff,
auditoría, configuración visual mínima y pruebas de recuperación.
