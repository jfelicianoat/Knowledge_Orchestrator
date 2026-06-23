# Fase 3 — Frontera con AI Broker

## Responsabilidades

El Orchestrator construye prompts, divide entradas, crea workflows, persiste dependencias, reintenta envíos y valida resultados. El Broker se limita a recibir una inferencia completa, encolarla, elegir el LLM y devolver su resultado.

Cada tarea Broker representa exactamente una inferencia. El Orchestrator puede enviar rápidamente todos los chunks independientes: un `202 queued` es una aceptación normal y no bloquea los siguientes envíos. El Broker debe consumir su cola de forma estrictamente serial, con una sola inferencia LLM activa globalmente.

## Flujo durable

1. Una captura enriquecida genera un workflow `single` o `chunked`.
2. Los prompts se renderizan localmente y se validan contra el contrato v1 antes de persistirse y antes del POST.
3. El dispatcher reclama tareas `READY` de una en una y persiste la aceptación `202` como `QUEUED`.
4. El poller consulta independientemente las tareas activas. Una tarea lenta puede seguir `queued` o `processing` mientras se envían y consultan las demás.
5. Cuando todos los chunks terminan, se crea una inferencia de síntesis dependiente de ellos.
6. La respuesta se valida antes de modificar el workflow. Una respuesta mal formada produce un error explícito.

Si el proceso cae con una tarea `SUBMITTING`, el arranque la devuelve a `READY` conservando `task_id` e `idempotency_key`. Un Broker conforme debe reconocer la operación original y no ejecutar una segunda inferencia.

## Reintentos y operación

Solo se reintentan timeouts, errores de conexión, `429`, `502`, `503` y `504`, con backoff configurable. Los errores permanentes y los incumplimientos de contrato terminan el workflow.

El catálogo de modelos se consulta periódicamente en `GET /api/v1/models` y se conserva en SQLite. Además, el Orchestrator consulta proactivamente `/health` y publica eventos solo cuando cambia la disponibilidad. El worker usa `asyncio` en un hilo separado: no bloquea el watcher ni el hilo principal de la futura UI. La indisponibilidad del Broker genera eventos, pero no detiene la ingestión.

Valores predeterminados de `BrokerSettings`: Broker `http://broker-machine.local:8080`, polling 2 s, health check 10 s, dispatcher 0,5 s, descubrimiento 300 s, backoff 30/60/120 s y contexto estimado de 16 000 tokens.

## Verificación

Las pruebas cubren contratos, `202`, polling prolongado, errores transitorios, prompts, workflows simples, chunking, síntesis, envío sin esperar resultados, llamadas secuenciales al Broker, recuperación idempotente y catálogo de modelos. La integración real requiere que AI Broker esté desplegado y accesible.
