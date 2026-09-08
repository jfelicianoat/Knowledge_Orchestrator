# Knowledge API v1

La fase 11 añade gestión de fuentes con el permiso explícito `sources`.
Contratos, configuración y límites: [Source_Monitoring.md](Source_Monitoring.md).
La fase 12 añade revisión individual con el permiso independiente `review`.
Semántica y límites: [Maintenance_Review.md](Maintenance_Review.md).
La fase 14 añade políticas, simulaciones, autorizaciones y pausa con el permiso
independiente `governance`: [Automation_Governance.md](Automation_Governance.md).

## Arranque local

La API es una frontera adicional del runtime existente. Se inicia explícitamente con
`python -m knowledge_orchestrator.app --api --api-port 8766` y escucha en
`http://127.0.0.1:8766/api/v1`. El modo API inicia los workers; no ejecutar dos runtimes
contra la misma raíz de datos. `--root` permite una raíz aislada para pruebas.

Configurar `KO_API_CLIENTS` con un array JSON de consumidores:

```json
[
  {
    "name": "mi-aplicacion",
    "token": "<token-aleatorio-de-al-menos-32-caracteres>",
    "scopes": ["read", "query", "ingest"]
  }
]
```

Generar cada token con un generador criptográfico y proporcionarlo mediante el entorno
del proceso. No usar el placeholder del ejemplo. Cada consumidor necesita nombre y token
únicos. La configuración se valida al arrancar; no existe acceso anónimo por defecto.
Las credenciales solo se mantienen como hashes en memoria y no se guardan en SQLite.
Rotar retirando el token del entorno y reiniciando el servicio.
El token del Broker es independiente, mediante `KO_BROKER_ADMIN_TOKEN` o el almacén protegido existente.

Todas las solicitudes, incluida OpenAPI, necesitan `Authorization: Bearer <token>`.
`read` permite consultar la bóveda configurada completa; no implementa restricciones por carpeta.
`query` permite hacer preguntas sobre esa bóveda y recuperar únicamente consultas propias.
`ingest` permite aportar documentos y ver únicamente las ingestas de ese consumidor.
`sources` permite administrar fuentes vigiladas y sus novedades.
`review` permite editar/aprobar/rechazar propuestas y revisar vigencia de claims.
`governance` permite administrar todas las políticas y consultar su auditoría en este
runtime. No está incluido en los demás permisos ni se concede automáticamente.
El nombre del consumidor identifica al actor auditado; no se acepta un actor enviado en el cuerpo.

## Contrato y rutas

`GET /openapi.json` describe rutas, permisos, schemas, parámetros, respuestas y errores.
Los cuerpos POST usan JSON estricto; no se aceptan propiedades desconocidas, claves duplicadas,
valores no finitos, parámetros repetidos ni cuerpos mayores de 2 MiB. Se requiere Content-Length.
Las listas admiten `limit` (1–1000) y `offset` (0–1.000.000), salvo donde OpenAPI indique otra cosa.

| Operación | Ruta | Permiso |
|---|---|---|
| Estado y bóveda | GET /status, /vaults | read |
| Documentos | GET /documents, /documents/{id} | read |
| Revisiones de nota | GET /documents/{id}/history | read |
| Entidades | GET /entities, /entities/{id} | read |
| Claims y evidencia | GET /claims, /claims/{id} | read |
| Transiciones y sucesión | GET /claims/{id}/history | read |
| Conocimiento de entidad | GET /knowledge/{id} | read |
| Histórico de entidad | GET /knowledge/{id}/history | read |
| Búsqueda FTS | GET /search?q=... | read |
| Búsqueda vectorial | POST /search/semantic | read |
| Pregunta fundamentada | POST /query, GET /queries/{id} | query |
| Ingesta | POST /documents, POST /ingestions, GET /ingestions/{id} | ingest |
| Propuestas existentes | GET /review-tasks, /review-tasks/{id} | read |
| Editar/regenerar propuesta | PATCH /review-tasks/{id} | review |
| Resolver propuesta | POST /review-tasks/{id}/approve, /reject | review |
| Revisar vigencia | PATCH /claims/{id}/knowledge-state | review |

Las rutas de fuentes están documentadas en `Source_Monitoring.md` y OpenAPI.
La aprobación masiva se describe más abajo; las rutas de políticas se describen en
`Automation_Governance.md` y OpenAPI.
La API no ofrece una ruta que sustituya directamente claims ni notas.

## Revisión individual

GET `/review-tasks/{id}` conserva los campos existentes y añade `review` con revisión,
evaluación congelada, versiones, actor y sucesor aplicado. PATCH recibe
`expected_revision`, `relation`, `confidence`, `impact`, `rationale` y `replacement_text`
(nullable para relaciones sin reemplazo). Cada edición crea una versión auditable.
El texto propuesto debe conservar la cita exacta; una revisión antigua devuelve 409.

POST `/review-tasks/{id}/approve` y `/reject` reciben `expected_revision` y opcionalmente
`reason`. Repetir una decisión ya finalizada sobre la misma revisión devuelve su recibo;
no crea otra publicación. Una decisión contraria o una revisión distinta devuelve 409.
Estas operaciones usan idempotencia del recurso/revisión; no crean trabajos nuevos por
una cabecera Idempotency-Key. El actor procede del consumidor autenticado.

PATCH `/claims/{id}/knowledge-state` recibe `expected_revision`, `state` y `reason`.
Admite CURRENT, DISPUTED, UNCERTAIN y REVIEW_REQUIRED; conserva documentos e histórico.
Rechaza revisiones obsoletas, manual_lock y dependencias de una publicación pendiente.
La vuelta a CURRENT no evita los filtros de coherencia/procedencia ni resuelve por sí
sola otra propuesta de contradicción abierta.

## Vigencia y documentos

Las consultas de claims, búsqueda y conocimiento admiten `state=current|historical|all`.
El valor por defecto es `current`; excluye histórico, claims disputados o inciertos, notas
no publicadas, aplicaciones pendientes y notas que la reconciliación observa en conflicto.
También excluye proyecciones cuya cadena de evidencia original dejó de estar vigente
o coherente, y claims involucrados en contradicciones abiertas.
`historical` incluye HISTORICAL y SUPERSEDED. Cada claim declara su estado, revisión, fechas,
entidades, sucesores, evidencia y fuente. `CURRENT` no constituye verificación factual independiente.

Los documentos se devuelven como Markdown con `knowledge_state=mixed_document`: una nota
puede contener afirmaciones con distinta vigencia. Consumir `/claims` o `/knowledge` para
filtrar conocimiento vigente. Una edición externa de un documento produce 409 hasta
reconciliarla; no se sirve silenciosamente contenido distinto del registrado.
Los endpoints `/history` conservan estados originales y etiquetan los sucesores actuales.

## Ingesta durable

Enviar `Idempotency-Key` (8–200 caracteres ASCII alfanuméricos o `_.:-`) y:

```json
{"title":"Documento de ejemplo","content":"Texto aportado por el consumidor","source_url":"https://example.org/doc"}
```

`source_url` es opcional, solo procedencia; la API no descarga esa URL. El servidor construye
el contrato de captura v1 y valida antes de registrar la intención. El worker entrega al inbox
y la ingesta, clasificación, Broker y publicación siguen los servicios existentes.
La respuesta 202 contiene `ingestion_id`, `capture_id` y `Location`. GET sobre Location
devuelve el estado de entrega y `capture_status` del flujo existente.

La misma clave y cuerpo devuelven la misma ingesta. Reutilizar la clave con otro cuerpo da
409. La intención persiste antes de escribir el archivo; la recuperación reconoce un archivo
ya entregado o una captura ya registrada. No acepta rutas de archivo del consumidor.

## Query con IA

POST `/query`, con `Idempotency-Key` y:

```json
{"question":"¿Qué versión de Producto X está vigente?","state":"current"}
```

Devuelve 202 mientras el Broker trabaja y `Location: /api/v1/queries/{query_id}`.
GET sobre Location devuelve 202 mientras está pendiente, 200 al completar, 502 ante un
resultado inválido/fallo y 409 si el conocimiento cambió durante o después de la respuesta.
Ante 409, hacer una consulta nueva con otra clave. El GET no reenvía trabajo al Broker.
Un reinicio reanuda la solicitud con la misma clave idempotente del Broker.

El Orchestrator recupera candidatos mediante FTS; la IA selecciona cuáles responden y si
son suficientes. La respuesta se compone de **citas exactas** de la evidencia seleccionada
(`answer_mode=evidence_quotes`), junto a claims, fuentes, estado, incertidumbres y fecha.
IDs inventados, texto de respuesta fuera del schema o evidencia no disponible invalidan
el resultado. No se publica texto libre del modelo como un hecho verificado.
Si no hay candidatos, devuelve 200 e insuficiencia explícita sin llamar al Broker.

La pregunta y la evidencia son datos no confiables dentro del prompt. No se habilitan
herramientas ni operaciones de escritura para consultas. La prueba de prompt injection
verifica esta frontera y el rechazo de IDs inventados; no demuestra que un LLM sea inmune
a toda selección semántica errónea. El usuario puede inspeccionar las citas devueltas.

El contexto está acotado a 24 candidatos y 60.000 caracteres. La respuesta no demuestra
que no exista otra evidencia fuera de la recuperación. Cambios en el corpus invalidan
conservadoramente respuestas previas; no se reutiliza una respuesta antigua como vigente.

## Búsqueda semántica

```json
{"vector":[0.1,0.7,0.2],"model":"modelo-del-indice","state":"current","limit":20}
```

POST `/search/semantic` calcula similitud coseno sobre los embeddings existentes que
coincidan en modelo y dimensiones, filtrando vigencia antes de ordenar. El consumidor
debe aportar un vector del mismo espacio. Si el índice no dispone de ese modelo/dimensión,
la lista está vacía. No se sustituye la operación por búsqueda léxica ni se simula un vector.
La generación de embeddings desde texto no forma parte de este endpoint.

## Evaluación individual por políticas

El detalle individual `GET /review-tasks/{id}` incluye en `review.automation_review`
una explicación de evaluación por políticas y `selection` con `candidate_id` y
`expected_revision` exactos. Este bloque no autoriza publicación ni cambia snapshots
históricos. El consumidor con permiso `governance` puede enviar esa selección a la
simulación de una política elegida explícitamente. El assessment nuevo distingue
`policy_evaluated=false` de la elegibilidad calculada por cada simulación; los antiguos
pueden conservar `NO_APPROVED_POLICY`. Véase [Maintenance_Review.md](Maintenance_Review.md).

## Revisión por lotes

Las cuatro rutas requieren permiso `review`. El consumidor solo puede consultar y
confirmar sus propios lotes. Los POST requieren `Idempotency-Key`.

- `POST /review-batches/preview`: `{"selection":[{"candidate_id":1,"expected_revision":1}]}`
  fija la selección; `{}` toma una instantánea de todas las propuestas pendientes.
  Devuelve 200 con plan, hash, recuentos, acciones y exclusiones. No publica notas.
- `POST /review-batches/{batch_id}/confirm`: `{"plan_hash":"<hash de la vista previa>"}`
  confirma exactamente ese plan y devuelve 202/Location. El worker local ejecuta
  únicamente los elementos elegibles, revalidando cada propuesta antes de escribir.
- `GET /review-batches/{batch_id}` devuelve el plan y los resultados individuales.
- `GET /review-batches?limit=100&offset=0` permite recuperar el historial propio.

La clave de preview es idempotente por consumidor y selección: repetirla devuelve el
mismo lote aunque hayan aparecido propuestas nuevas; reutilizarla con otro cuerpo da
409. Repetir la confirmación del mismo hash no crea otra ejecución. El hash incorrecto
da 409. Un lote ajeno no está disponible (404).

Estados de lote: `DRAFT`, `READY`, `RUNNING`, `RECOVERY_REQUIRED`, `COMPLETE`.
Resultados de elementos: `PENDING`, `RUNNING`, `SKIPPED`, `APPLIED`, `CONFLICT`, `FAILED`,
`EXTERNALLY_RESOLVED`. COMPLETE significa que hay un resultado para cada tarea, no que
todas se hayan aplicado. Los éxitos ajenos al lote no se contabilizan como aplicaciones
del lote. RECOVERY_REQUIRED indica una intención interrumpida; el arranque recupera
primero las publicaciones y después sus recibos. Se requiere el runtime activo para
ejecutar los lotes confirmados; servir solo el adaptador WSGI no arranca workers.

Límites: 1000 propuestas y 8 MiB de vista previa por lote, con error explícito al
superarlos. Las propuestas que escriben una misma nota o dependen de la nota que otra
modifica quedan excluidas para revisión por separado. No se reordena ni se regenera
silenciosamente un plan confirmado. Los bloqueos manuales permanecen efectivos.

## Reversión de publicaciones

Cinco rutas con permiso `review` permiten listar publicaciones aplicadas, preparar una
reversión y consultar/confirmar sus recibos. La confirmación exige el hash del plan
revisado y un motivo; conserva el historial y vuelve a validar bloqueos, evidencia y
contenido actual. Los planes se aíslan por consumidor y omiten rutas de archivos.
Los POST requieren `Idempotency-Key`; la confirmación repetida del mismo plan/hash/motivo
es idempotente. Contratos y operación: [Maintenance_Reversion.md](Maintenance_Reversion.md).

- `GET /review-publications`
- `GET /review-reversions`
- `POST /review-reversions/preview`
- `GET /review-reversions/{reversion_id}`
- `POST /review-reversions/{reversion_id}/confirm`

El flujo autenticado de vista previa y confirmación está probado por HTTP real en
loopback con notas temporales. Esto no acredita la conexión externa al Broker.

## Operación y alcance de despliegue

La pantalla **Servicios → API y consumidores** permite iniciar/detener el listener de
esta sesión y consultar actividad. La CLI `--api` usa el mismo controller, tras recuperar
el runtime. El estado mostrado no detecta servidores de otros procesos. Un puerto
ocupado produce un error explícito; no se toma su servicio como propio.

Los consumidores se cargan desde `KO_API_CLIENTS` al iniciar el listener. Las credenciales
y permisos quedan fijados en memoria durante esa ejecución; cambios de configuración
se aplican al detener/iniciar. La pantalla muestra nombres/permisos, nunca tokens ni sus
hashes. Consumidores vistos anteriormente sin acceso configurado se distinguen como
históricos. Los recuentos y la paginación abarcan las últimas 1000 solicitudes registradas;
no son métricas de todo el histórico. Las rutas no reconocidas se muestran como `unmatched`.

**Servicios → Automatizaciones** muestra los workers de vigilancia, análisis y lotes
confirmados. Su estado indica que el proceso local está activo, no que el Broker esté
disponible ni que una tarea haya concluido. Las políticas automáticas y sus controles
se documentan en `Automation_Governance.md`; un lote confirmado por una persona conserva esa atribución.

El servidor incluido utiliza WSGI estándar y es **local, en loopback**. No incluye TLS,
proxies ni exposición a Internet. Para otro despliegue, montar `KnowledgeApi` en un servidor
WSGI apropiado detrás de TLS y controles de capacidad; no cambiar el bind local sin evaluar
ese despliegue. No hay cookies ni CORS permisivo. Las respuestas llevan `Cache-Control: no-store`.
Los eventos registran consumidor, ruta normalizada, método, estado e identificador, sin
tokens, cuerpos ni texto de preguntas. Queries e ingestas conservan su auditoría transaccional.

## Evidencia de fase 10

La prueba HTTP real en loopback devolvió 200 autenticado y 401 sin credencial. Las pruebas
de contrato usan WSGI y Broker simulado, incluyendo recuperación, idempotencia, evidencias
inventadas, aislamiento de consumidores y cambios de conocimiento.
La conexión real al Broker 192.168.1.52:8765 está pendiente: Windows denegó el socket saliente
con error 10013 antes de recibir HTTP. No se pudo validar su token ni ejecutar inferencia real.
