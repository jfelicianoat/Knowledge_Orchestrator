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
2. Ante creación o cambio, comprobar tamaño y `mtime` cada segundo hasta obtener dos lecturas iguales.
3. Analizar frontmatter y cuerpo según el contrato v1. Los ficheros sin transcripción pasan a `failed` con `TRANSCRIPTION_MISSING`.
4. Insertar la captura y moverla a `processing` en una operación lógica de reclamación. Si `capture_id` ya existe, mover el duplicado a `failed/duplicates` sin reenviarlo.
5. Los campos de YouTube solo son obligatorios cuando `source_type: youtube`.

### Estados y recuperación

Estados persistidos: `PENDING`, `SUBMITTING`, `QUEUED`, `PROCESSING`, `COMPLETED`, `FAILED`, `REJECTED` y `CANCELLED`.

- Al arrancar, reconciliar SQLite con las carpetas. `SUBMITTING`, `QUEUED` y `PROCESSING` se consultan por `task_id`; no se crean tareas nuevas sin comprobar primero la existente.
- Reintentar únicamente desconexión, `429`, `502`, `503`, `504` y timeout, con backoff 30/60/120 segundos y máximo tres intentos.
- Errores de contrato, transcripción ausente, presupuesto agotado o cancelación son terminales.

### Temas, vigencia y perfiles

- Los temas se evalúan por orden de configuración; gana el primero con coincidencia de palabras clave. Sin coincidencia, la nota va a `_inbox`.
- Cada tema incluye `folder`, `keywords`, `default_profile`, `is_updatable`, `obsolescence_days` y `auto_review`.
- `obsolescence_days: null` significa que nunca caduca. El Revisor de Vigencia lista notas vencidas y ofrece reprocesar, archivar, mantener vigente o eliminar.
- Los perfiles editables contienen `system_prompt`, `user_prompt`, `chunk_prompt`, `synthesis_prompt`, `preferred_model`, `fallback_allowed`, temperatura y límites de salida.

### Broker y publicación

- Crear tareas mediante `POST /api/v1/tasks` y consultar `GET /api/v1/tasks/{task_id}` cada dos segundos mientras sean activas.
- El bucle de envío no espera el resultado de una tarea para enviar la siguiente. Tras persistir la respuesta `202`, el seguimiento pasa al poller y el dispatcher continúa con el siguiente fichero.
- El Orchestrator no interpreta `queued` como bloqueo o error: el Broker ejecuta globalmente una sola tarea LLM y las restantes esperan de forma normal.
- En éxito, validar que `result_markdown` no contiene frontmatter y construir el frontmatter final de forma segura con un serializador YAML.
- Escribir primero a un fichero temporal en la carpeta destino y renombrarlo atómicamente.
- Mover el origen a `completed` solo después de publicar la nota y persistir su ruta.
- Rechazar desde la UI mueve la nota a `C:/YT-Pipeline/rejected/notes`, mueve el origen a `rejected/sources` y conserva ambos paths. Reprocesar devuelve una copia del origen a `processing` con un nuevo `task_id`, conservando el mismo `capture_id` y aumentando `revision`.

### Criterios de aceptación

- La UI permanece responsive durante watchdog, polling y llamadas largas.
- Un reinicio no duplica tareas ni notas.
- Se procesan fuentes YouTube y no YouTube con metadata parcial.
- La publicación, rechazo y reprocesado son reversibles y quedan auditados.
- El Broker offline acumula trabajo y se recupera automáticamente.
- Una tarea LLM lenta no bloquea la ingestión ni el envío de las siguientes; todas quedan registradas y visibles mientras el Broker las ejecuta una a una.
