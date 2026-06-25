# Agent: Knowledge Orchestrator (Desktop App)

> **Precedencia:** la sección `Contrato Normativo del MVP` es obligatoria para la implementación.



## Stack Tecnológico Definido



**UI Framework:** CustomTkinter (tema oscuro por defecto)

**File Monitoring:** watchdog (detección de nuevos archivos)

**HTTP Client:** httpx (comunicación asíncrona con Broker)

**Gráficos:** matplotlib (integrado en tkinter canvas)

**Configuración:** PyYAML (archivos de configuración)



## Arquitectura de la UI (Ventana Única con Menú Lateral)



### Layout Principal

```

┌──────────────────────────────────────────────────────────────┐

│  Knowledge Orchestrator                          [─][□][✕]   │

├──────────────┬───────────────────────────────────────────────┤

│  📊 Dashboard│         [Contenido Pestaña Activa]            │

│  🔄 Cola     │                                               │

│  📝 Revisión │                                               │

│  🗂️ Temas    │                                               │

│  ⚙️ Config   │                                               │

├──────────────┤                                               │

│ 🟢 Broker OK │                                               │

│ 3 pendientes │                                               │

└──────────────┴───────────────────────────────────────────────┘

```



## Pestaña 1: Dashboard (Métricas y Monitorización)



### Elementos Visuales

**Métricas en Tiempo Real:**

- Videos procesados hoy/semana

- Tiempo medio de procesamiento

- Tasa de error

- Coste acumulado APIs externas



**Gráfico de Actividad Temporal (matplotlib):**

- Barras por día/hora de actividad

- Distribución por temas (gráfico circular)

- Tendencias de uso de modelos



### Layout del Dashboard

```

┌────────────────────────┬────────────────────────────────────┐

│  MÉTRICAS HOY          │  Actividad últimos 7 días         │

│  ┌────┐ ┌────┐ ┌────┐ │  ▁▃▅▂▇▄█ (matplotlib bars)       │

│  │ 12 │ │ 3  │ │47m │ │                                    │

│  │Vids│ │Err │ │T.M │ │  Estado Broker IA                  │

│  └────┘ └────┘ └────┘ │  🟢 llama3.1:70b                  │

│                        │  🟢 llama3.1:8b                   │

│  ESTA SEMANA           │  🟡 deepseek (0.8€/5€)            │

│  ┌────┐ ┌────┐        │                                    │

│  │ 67 │ │0.8€│        │                                    │

│  │Vids│ │API │        │                                    │

│  └────┘ └────┘        │                                    │

└────────────────────────┴────────────────────────────────────┘

```



## Pestaña 2: Cola Visual (Pipeline Animado)



### Concepto de "Bolas en Cañería"

**Implementación:** Canvas de CustomTkinter con círculos conectados por líneas

**Colores de Estado:** 

- Gris (Pendiente)

- Azul pulsante (Procesando) 

- Verde (Completado)

- Rojo (Error, rebote visual)



### Layout de la Cola

```

┌─────────────────────────────────────────────────────────────┐

│  PIPELINE VISUAL                                            │

│  ┌─────────┐         ┌─────────┐         ┌─────────┐       │

│  │ ● ● ●   │═══════▶ │ ●●●     │═══════▶ │ ✓ ✓ ✓   │       │

│  │PENDIENTE│         │PROCESANDO│         │COMPLETADO│       │

│  └─────────┘         └─────────┘         └─────────┘       │

│                           │                                 │

│                      ┌────▼────┐                           │

│                      │ ERROR ● │ ← Rebote visual           │

│                      └─────────┘                           │

├─────────────────────────────────────────────────────────────┤

│  TAREAS ACTIVAS                                             │

│  🔵 "Cómo configurar Ollama..." │ llama3.1:70b │ 2:34      │

│     ████████████████░░░░░░ 68%  │ [Cancelar]               │

│  SIGUIENTE: "Estrategias Trading..." │ deepseek │ queued    │

│     Esperando a que termine la tarea activa                 │

├─────────────────────────────────────────────────────────────┤

│  COLA PENDIENTE                                             │

│  ⚪ "Python Async Patterns..." [↑][↓][✕]                   │

│  ⚪ "DeepSeek vs GPT4 Review..." [↑][↓][✕]                 │

│  ⚪ "Análisis Técnico BTC..." [↑][↓][✕]                    │

└─────────────────────────────────────────────────────────────┘

```



## Pestaña 3: Revisión (Historial y Validación)



### Funcionalidad de Revisión Post-Procesamiento

**Objetivo:** Revisar notas generadas, rechazar/aceptar, reprocesar desde fuente

La misma pestaña incorpora candidatos de actualización semántica con evidencia, comparación lado a lado, diff, confianza, impacto y acciones aprobar/rechazar/mantener vigente. La aprobación es obligatoria antes de sobrescribir una nota existente.



### Layout Split

```

┌──────────────────────────┬──────────────────────────────────┐

│  FILTROS Y LISTA         │  PREVIEW Y ACCIONES              │

│  [Todos temas ▼]         │  "Cómo configurar Ollama"        │

│  [Última semana ▼]       │  ─────────────────────────────   │

│  [Buscar... 🔍]          │  Tema: IA-y-LLMs                │

│                          │  Modelo: llama3.1:70b           │

│  ✅ Cómo configurar...   │  Procesado: 20 jun 2024         │

│     20 jun · IA-LLMs     │                                  │

│  ✅ Estrategias de...    │  [Markdown preview scrollable]   │

│     19 jun · Trading     │                                  │

│  ✅ Python Async...      │                                  │

│     19 jun · Desarrollo  │  ┌──────────┐ ┌─────────────┐   │

│                          │  │✅ Aceptar │ │❌ Rechazar  │   │

│                          │  └──────────┘ └─────────────┘   │

│                          │  ┌─────────────────────────┐     │

│                          │  │🔄 Reprocesar Original   │     │

│                          │  └─────────────────────────┘     │

└──────────────────────────┴──────────────────────────────────┘

```



## Pestaña 4: Gestión de Temas



### Funcionalidad de Configuración de Temas

- **Auto-detección:** Basada en palabras clave del título/canal

- **Carpetas dinámicas:** Creación automática en Obsidian si no existen

- **Perfiles por tema:** Diferentes prompts según el contenido



### Layout Split

```

┌─────────────────────┬───────────────────────────────────────┐

│  LISTA DE TEMAS     │  CONFIGURACIÓN DEL TEMA SELECCIONADO │

│  🗂️ IA-y-LLMs       │  Nombre: [IA-y-LLMs            ]     │

│  🗂️ Desarrollo      │  Carpeta: [Knowledge/IA-y-LLMs ]     │

│     └ Python        │  Palabras clave:                      │

│     └ Web           │  [ollama,llm,ia,gpt,neural...  ]     │

│  🗂️ Trading         │                                       │

│     └ Estrategias   │  Obsolescencia:                       │

│                     │  ○ Nunca  ● Cada [180] días          │

│  [+ Nuevo Tema]     │                                       │

│                     │  Modelo preferido:                    │

│                     │  [llama3.1:70b            ▼]         │

│                     │                                       │

│                     │  Perfil de extracción:               │

│                     │  [Técnico Profundo        ▼]         │

│                     │                                       │

│                     │  [Guardar] [Eliminar Tema]           │

└─────────────────────┴───────────────────────────────────────┘

```



## Pestaña 5: Configuración



### Secciones de Configuración

**Rutas del Sistema:**

- Carpeta inbox (donde deposita el plugin)

- Vault de Obsidian

- Carpetas de trabajo (processing, completed, failed)



**Conexión al Broker IA:**

- Hostname/IP de la máquina del Broker

- Puerto (default: 8080)

- Test de conectividad



**Procesamiento:**

- Tareas simultáneas máximas

- Horarios activos (inicio/fin)

- Intervalo de verificación



**Perfiles de Extracción:**

- Editor de system_prompt y user_prompt

- Variables disponibles: {title}, {channel}, {transcript}, {published_date}

- Configuración de temperatura y max_tokens



## Lógica Core del File Watcher



### Monitorización Inteligente

```python

class FileWatcher:

    def on_created(self, event):

        if event.src_path.endswith('.md'):

            # 1. Validar estructura frontmatter

            # 2. Verificar has_transcript

            # 3. Si válido, aplicar auto-detección de tema  

            # 4. Construir payload para Broker

            # 5. Enviar request HTTP

            # 6. Mover archivo a /processing/

```



### Estados de Procesamiento

- **PENDING:** En inbox/, esperando procesamiento

- **PROCESSING:** Enviado al Broker, esperando respuesta

- **COMPLETED:** Procesado exitosamente, guardado en Obsidian

- **FAILED:** Error en cualquier paso, movido a /failed/

- **REJECTED:** Rechazado desde UI, movido a /rejected/



## Comunicación con el Broker IA

> Los payloads históricos quedan sustituidos por el contrato v2 descrito en `Data_Contracts.md` y las fixtures de `docs/contracts`. La fase 5 extenderá esta base para Multitasking_LLM; véase `docs/Study_Multitasking_LLM.md`.



### Payload de Request

```json

{

  "task_id": "proc_20240620_143022_dQw4w9WgXcQ",

  "profile": {

    "name": "Técnico Profundo",

    "system_prompt": "Eres un experto analista...",

    "user_prompt": "Título: {title}\\nCanal: {channel}\\n\\nTranscripción:\\n{transcript}",

    "preferred_model": "llama3.1:70b",

    "temperature": 0.3,

    "max_tokens": 4000

  },

  "content": {

    "transcript": "...",

    "metadata": {

      "title": "...",

      "channel": "...",

      "source_type": "youtube"

    }

  }

}

```



### Manejo de Respuestas

- **Success:** Escribir resultado en Obsidian, mover fuente a /completed/

- **Error:** Log detallado, mover a /failed/ con información del error

- **Timeout:** Reintentar hasta 3 veces con backoff exponencial

## Contrato Normativo del MVP

### Capas y responsabilidades

- **UI:** renderiza estado y envía comandos; no accede directamente a HTTP, SQLite ni al filesystem.
- **Servicios:** coordinan ingestión, clasificación, envío, publicación, rechazo y reprocesado.
- **Repositorios:** encapsulan SQLite y movimientos de archivos.
- **Worker:** posee el bucle `asyncio`, reintentos, polling y cancelación. Comunica eventos inmutables a Tk mediante una cola thread-safe; solo el hilo principal modifica widgets.

La base `C:/YT-Pipeline/state/orchestrator.db` conserva capturas, tareas, intentos, notas publicadas, temas, perfiles y métricas. `capture_id` es único.

### Ingestión robusta y fuentes genéricas

1. Vigilar por defecto `%USERPROFILE%/Downloads/YT-Knowledge-Inbox`; la ruta es editable.
2. Ante creación o cambio, comprobar tamaño y `mtime` cada segundo hasta obtener tres lecturas consecutivas iguales.
3. Si la apertura falla por bloqueo, reintentar tres veces con esperas de 1, 2 y 4 segundos. Tras el tercer fallo, registrar `FILE_LOCKED`, mantener el original en inbox y ofrecer reintento manual desde la UI.
4. Analizar frontmatter y cuerpo según el contrato v1 antes de cualquier procesamiento. Un contrato inválido pasa a `failed/contracts` con sidecar JSON que contiene código, campo y mensaje; nunca se envía al Broker.
5. Los ficheros sin transcripción pasan a `failed` con `TRANSCRIPTION_MISSING`.
6. Copiar a `staging/*.part`, sincronizar a disco, calcular hash y revalidar la copia.
7. Insertar la captura `STAGED` en SQLite y confirmar. Solo entonces mover la copia a `processing` mediante `os.replace`, actualizarla a `PENDING` y retirar el original de inbox.
8. Si `capture_id` ya existe, mover el duplicado a `failed/duplicates` sin reenviarlo.
9. Los campos de YouTube solo son obligatorios cuando `source_type: youtube`.

### Estados y recuperación

Estados persistidos: `STAGED`, `PENDING`, `SUBMITTING`, `QUEUED`, `PROCESSING`, `COMPLETED`, `FAILED`, `REJECTED` y `CANCELLED`.

- Al arrancar, reconciliar SQLite con las carpetas. `SUBMITTING`, `QUEUED` y `PROCESSING` se consultan por `task_id`; no se crean tareas nuevas sin comprobar primero la existente.
- Los registros `STAGED` se reconcilian primero: si existe staging válido se completa el movimiento; si ya está en processing se actualiza a `PENDING`; si falta en ambos lugares se conserva inbox o se marca `STAGING_FILE_MISSING`.
- Reintentar únicamente desconexión, `429`, `502`, `503`, `504` y timeout, con backoff 30/60/120 segundos y máximo tres intentos.
- Errores de contrato, transcripción ausente, presupuesto agotado o cancelación son terminales.

### Temas, vigencia y perfiles

- Los temas se evalúan por orden de configuración; gana el primero con coincidencia de palabras clave. Sin coincidencia, la nota va a `_inbox`.
- Cada tema incluye `folder`, `keywords`, `default_profile`, `is_updatable`, `obsolescence_days` y `auto_review`.
- `obsolescence_days: null` significa que nunca caduca. El Revisor de Vigencia lista notas vencidas y ofrece reprocesar, archivar, mantener vigente o eliminar.
- Los perfiles editables contienen `system_prompt`, `user_prompt`, `chunk_prompt`, `synthesis_prompt`, `preferred_model`, `fallback_allowed`, temperatura y límites de salida.

### Orquestación completa de inferencias

- El Orchestrator renderiza los prompts, resuelve placeholders y calcula si el contenido cabe antes de crear una tarea Broker.
- Si necesita chunking, divide localmente por límites naturales, crea una inferencia Broker por chunk, valida cada respuesta y finalmente crea otra inferencia para síntesis.
- Una tarea Broker contiene el prompt final o una entrada de embedding. Puede solicitar estrategia técnica `single` o, tras la fase 5, `mixture_of_agents`; nunca delega al Broker el workflow de conocimiento, el chunking ni decisiones sobre Obsidian.
- El Orchestrator conserva `workflow_id`, pasos, dependencias, resultados parciales y reanudación. El Broker recibe correlación opaca en `content.metadata` y genera su propio `task_id`.
- Si el Broker devuelve `CONTEXT_LIMIT_EXCEEDED`, el Orchestrator recalcula chunks; no espera que el Broker trunque o divida.

### Broker y publicación

- Crear tareas mediante `POST /api/v1/tasks` y consultar `GET /api/v1/tasks/{task_id}` cada dos segundos mientras sean activas.
- Validar el payload completo contra el esquema Broker v2 inmediatamente antes del POST y validar cada respuesta antes de actualizar SQLite. Un incumplimiento produce `CONTRACT_VALIDATION_FAILED`, sin reintento automático.
- El bucle de envío no espera el resultado de una tarea para enviar la siguiente. Tras persistir la respuesta `202`, el seguimiento pasa al poller y el dispatcher continúa con el siguiente fichero.
- El Orchestrator no interpreta `queued` como bloqueo o error: el Broker mantiene inicialmente un solo workflow activo y las restantes tareas esperan. Multitasking_LLM puede introducir concurrencia interna dentro de ese workflow sin autorizar varios workflows simultáneos.
- En éxito, validar `result.result_markdown`, normalizarlo internamente y comprobar que no contiene frontmatter antes de construirlo con un serializador YAML seguro.
- Escribir primero a un fichero temporal en la carpeta destino y renombrarlo atómicamente.
- Mover el origen a `completed` solo después de publicar la nota y persistir su ruta.
- Rechazar desde la UI mueve la nota a `C:/YT-Pipeline/rejected/notes`, mueve el origen a `rejected/sources` y conserva ambos paths. Reprocesar devuelve una copia del origen a `processing` con un nuevo `task_id`, conservando el mismo `capture_id` y aumentando `revision`.

### Mantenimiento semántico de Obsidian

**Implementado en fase 6:** la migración 007, los jobs Broker durables, los validadores de spans/evidencia, FTS5/embeddings opcionales, candidatos, diffs, aprobación explícita, snapshots y reemplazo atómico recuperable están operativos. **Implementado en fase 7:** la UI presenta candidatos `PENDING_REVIEW` con diff y permite aprobar o rechazar mediante los servicios de dominio existentes.

El Orchestrator es el único responsable de decidir, proponer y aplicar actualizaciones:

1. Indexar notas en `knowledge_claims` con afirmación, entidades, tipo, volatilidad, fecha de validez, fuentes, spans y `manual_lock`.
2. Cuando entra una fuente nueva, extraer sus afirmaciones mediante un prompt construido por el Orchestrator y ejecutado como inferencia genérica por el Broker.
3. Recuperar candidatos mediante tema, entidades, SQLite FTS5 y, cuando se configure, embeddings solicitados al Broker y almacenados localmente.
4. Construir una inferencia de comparación con la afirmación existente y evidencia nueva; interpretar relaciones `supports`, `extends`, `contradicts`, `supersedes`, `unrelated` o `uncertain`.
5. Exigir evidencia local con `source_id` y span para toda propuesta. La memoria interna del LLM no constituye evidencia.
6. Generar operaciones de parche, diff legible, confianza e impacto. No sustituir contenido con `manual_lock`.
7. Mostrar la propuesta al usuario. Ninguna actualización semántica sobrescribe automáticamente una nota.
8. Tras aprobación, guardar la revisión anterior, aplicar el cambio atómicamente, actualizar fuentes y `last_verified_at`, y registrar auditoría completa.

La revisión por fechas solo crea candidatos. Sin una fuente nueva introducida explícitamente no puede producir una actualización factual. Quedan fuera del proyecto RSS, documentación vigilada, conectores automáticos a APIs y búsqueda autónoma en Internet.

### Criterios de aceptación

- La UI permanece responsive durante watchdog, polling y llamadas largas.
- Un reinicio no duplica tareas ni notas.
- Se procesan fuentes YouTube y no YouTube con metadata parcial.
- La publicación, rechazo y reprocesado son reversibles y quedan auditados.
- El Broker offline acumula trabajo y se recupera automáticamente.
- Una tarea Broker lenta no bloquea la ingestión ni el envío de las siguientes; todas quedan registradas y visibles mientras esperan. El Broker decide si el workflow activo usa una invocación o un consenso interno acotado.

### Integración Multitasking_LLM

- La política de fase 5 está implementada y permanece desactivada por defecto. Su activación productiva espera providers reales, catálogo y evaluación de consenso.
- `single` será el valor predeterminado. La estrategia se elegirá mediante política versionada del perfil/paso, no por instrucciones incluidas en el contenido.
- Los chunks y embeddings usan siempre `single`; solo síntesis finales o pasos `single` habilitados en el perfil pueden solicitar `mixture_of_agents/fast`.
- El Orchestrator persistirá estrategia, progreso, consenso, scheduling, uso, modelos y advertencias, pero no calculará VRAM ni coordinará proponentes.
- Consenso y confianza no constituyen evidencia. La publicación y el mantenimiento semántico seguirán requiriendo evidencia local.
- El fallback a `single` crea una tarea nueva y solo se admite para fallos tipados de quorum/capacidad, nunca presupuesto, privacidad o contrato.
- El análisis y los prerrequisitos están definidos en `docs/Study_Multitasking_LLM.md`.

### Feedback visual obligatorio

La cola visual es un requisito funcional de UX porque los trabajos pueden durar minutos:

- Mostrar siempre estado persistido, posición en cola, modelo elegido, fase actual, tiempo transcurrido, chunks completados y estado del Broker.
- Actualizar como máximo cada dos segundos sin bloquear el hilo de Tk.
- Usar animación continua solo para una tarea `PROCESSING`; las tareas `QUEUED` muestran orden y espera estimada cuando existan datos suficientes.
- No mostrar porcentajes inventados. Para trabajo sin progreso cuantificable usar fase, spinner y tiempo transcurrido.
- Los estados degradados, reintentos y espera por Broker offline deben ser visibles con texto accionable, no únicamente mediante color.
