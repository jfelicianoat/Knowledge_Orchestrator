# Fase 3 — Frontera con AI Broker

## Responsabilidades

El Orchestrator construye prompts, divide entradas, crea workflows, persiste dependencias, reintenta envíos y valida resultados. Esta fase implementa el baseline `single`: el Broker recibe una inferencia completa, la encola, elige el LLM y devuelve su resultado.

En `single`, cada tarea Broker representa exactamente una inferencia. El Orchestrator puede enviar rápidamente todos los chunks independientes: un `202 queued` es una aceptación normal y no bloquea los siguientes envíos. El contrato v2.7 admite declarar estrategia (`single`, `mixture_of_agents`, `agent` o `auto`), preset (`fast`/`slow` en mixture) y los estados no terminales `waiting_for_tools` y `waiting_for_memory`; en todos los casos se mantiene un solo workflow Broker activo. Las estrategias de petición y los estados terminales se validan de forma estricta. Las fases intermedias son aditivas: una fase nueva se conserva como `PROCESSING` y el poller continúa sondeando.

## Flujo durable

1. Una captura enriquecida genera un workflow `single` o `chunked`.
2. Los prompts se renderizan localmente y se validan contra el contrato Broker v2.7 antes de persistirse y antes del POST.
3. El dispatcher reclama tareas `READY` de una en una y persiste la aceptación `202` como `QUEUED`.
4. El poller consulta independientemente las tareas activas. Una tarea lenta puede seguir `queued` o `processing` mientras se envían y consultan las demás.
5. Cuando todos los chunks terminan, se crea una inferencia de síntesis dependiente de ellos.
6. La respuesta se valida antes de modificar el workflow. Una respuesta mal formada produce un error explícito.

Si el proceso cae con una tarea `SUBMITTING`, el arranque la devuelve a `READY` conservando `task_id` e `idempotency_key`. Un Broker conforme debe reconocer la operación original y no ejecutar una segunda inferencia.

## Reintentos y operación

Se reintentan timeouts, errores de conexión, `401`/`403` por credencial admin caducada, `429`, `502`, `503` y `504`, con backoff configurable. Los errores permanentes y los incumplimientos de contrato terminan el workflow. Un fallo al consultar `capabilities` genera una advertencia, pero no bloquea la planificación ni el envío: el `409` del endpoint de tareas sigue siendo la autoridad para una capacidad concreta.

El catálogo de modelos se consulta periódicamente en `GET /api/v1/models` y se conserva en SQLite. Además, el Orchestrator consulta proactivamente `/health` y publica eventos solo cuando cambia la disponibilidad. El worker usa `asyncio` en un hilo separado: no bloquea el watcher ni el hilo principal de la futura UI. La indisponibilidad del Broker genera eventos, pero no detiene la ingestión.

Valores predeterminados de `BrokerSettings`: Broker `http://broker-machine.local:8765`, polling 2 s, health check 10 s, dispatcher 0,5 s, descubrimiento 300 s, backoff 30/60/120 s y contexto estimado de 16 000 tokens.

## Verificación

Las pruebas cubren contratos, `202`, polling prolongado, errores transitorios, prompts, workflows simples, chunking, síntesis, envío sin esperar resultados, llamadas secuenciales al Broker, recuperación idempotente y catálogo de modelos. La integración real requiere que AI Broker esté desplegado y accesible.

El contrato quedó alineado después de esta fase y evolucionó hasta v2.7: creación idempotente, IDs separados, estados detallados (incluidos `waiting_for_tools` y `waiting_for_memory`), estrategias `single`/`mixture_of_agents`/`agent`/`auto`, preset `slow` y `result_markdown`. El estudio de Multitasking_LLM está en [`Study_Multitasking_LLM.md`](Study_Multitasking_LLM.md); la política por perfil decide qué pasos usan consenso o delegan la estrategia en el meta-router del Broker con `auto`.
