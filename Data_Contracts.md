# Data Contracts & Communication Schemas

> **Precedencia:** `Contratos Normativos v1` es el contrato interoperable del MVP. Las secciones 1-7 se conservan como ejemplos funcionales y contexto.



## 1. Plugin Chrome → Orchestrator (File System)



### Frontmatter YAML del Archivo .md

```yaml

---

capture_id: "yt_20240620_143022_dQw4w9WgXcQ"

source_type: "youtube"

video_id: "dQw4w9WgXcQ"

url: "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

title: "Cómo Configurar Ollama para Modelos Locales de IA"

knowledge_id: "ollama-configuration"

revision: 1

knowledge_status: "current"

last_verified_at: "2024-06-20T14:35:45Z"

source_versions: ["yt_20240620_143022_dQw4w9WgXcQ"]

channel: "TechChannel Pro"

channel_url: "https://www.youtube.com/@techchannelpro"

duration_seconds: 1725

published_date: "2024-05-10"

captured_at: "2024-06-20T14:30:22Z"

transcript_language: "es"

has_transcript: true

extraction_method: "schema_jsonld"

plugin_version: "1.0.0"

status: "pending"

---

```



### Cuerpo del Markdown

```markdown

# {title}



**Canal:** {channel}

**Duración:** {duration_formatted}

**Publicado:** {published_date}

**Capturado:** {captured_at}



## Transcripción



{transcript_content_with_timestamps}

```



## 2. Orchestrator → Broker (HTTP REST)



### POST /api/v1/extract

```json

{

  "task_id": "proc_20240620_143022_dQw4w9WgXcQ",

  "profile": {

    "name": "Técnico Profundo",

    "system_prompt": "Eres un experto analista de conocimiento técnico. Tu tarea es extraer exhaustivamente todos los conceptos, herramientas, técnicas y datos valiosos de transcripciones de video, organizándolos de manera estructurada para facilitar el aprendizaje y la referencia posterior.",

    "user_prompt": "Analiza esta transcripción de video de YouTube y extrae TODO el conocimiento valioso:\\n\\nTítulo: {title}\\nCanal: {channel}\\nFecha publicación: {published_date}\\n\\nTranscripción:\\n{transcript}\\n\\nGenera una nota completa en formato Markdown con estructura clara, conceptos técnicos detallados, herramientas mencionadas, y aplicaciones prácticas.",

    "preferred_model": "llama3.1:70b",

    "temperature": 0.3,

    "max_tokens": 4000

  },

  "content": {

    "transcript": "Texto completo de la transcripción...",

    "metadata": {

      "title": "Cómo Configurar Ollama para Modelos Locales de IA",

      "channel": "TechChannel Pro",

      "published_date": "2024-05-10",

      "source_type": "youtube",

      "video_id": "dQw4w9WgXcQ",

      "duration_seconds": 1725

    }

  }

}

```



## 3. Broker → Orchestrator (HTTP Response)



### Success Response

```json

{

  "task_id": "proc_20240620_143022_dQw4w9WgXcQ",

  "status": "success",

  "model_used": "llama3.1:70b",

  "result_markdown": "# Cómo Configurar Ollama para Modelos Locales de IA\\n\\n## Resumen Ejecutivo\\nEste tutorial cubre la instalación y configuración completa de Ollama...\\n\\n## Conceptos Técnicos Extraídos\\n\\n### Arquitectura de Ollama\\n- **Motor de inferencia:** Basado en llama.cpp optimizado\\n- **Gestión de memoria:** Carga dinámica de modelos según VRAM disponible\\n- **API REST:** Compatible con OpenAI para integración sencilla\\n\\n### Modelos Recomendados\\n- **Llama 3.1 8B:** Balance óptimo velocidad/calidad para uso general\\n- **Llama 3.1 70B:** Máxima calidad para tareas complejas (requiere 64GB+ RAM)\\n- **Qwen2.5 Coder:** Especializado en programación y análisis de código\\n\\n## Herramientas y Recursos Mencionados\\n\\n### Software Requerido\\n- **Docker:** Para instalación containerizada (opcional)\\n- **CUDA Toolkit:** Para aceleración GPU en NVIDIA\\n- **Git:** Para clonar repositorios de modelos customizados\\n\\n### Comandos Esenciales\\n```bash\\n# Instalación básica\\ncurl https://ollama.ai/install.sh | sh\\n\\n# Descargar modelo\\nollama pull llama3.1:8b\\n\\n# Ejecutar modelo\\nollama run llama3.1:8b\\n```\\n\\n## Aplicaciones Prácticas\\n\\n### Configuración para Desarrollo\\n1. **Instalación en servidor dedicado:** Separar la carga de GPU del equipo principal\\n2. **Configuración de red:** Exponer API en puerto 11434 para acceso remoto\\n3. **Gestión de modelos:** Script para descarga automática de nuevas versiones\\n\\n### Optimización de Rendimiento\\n- **VRAM mínima por modelo:** 8B necesita 8GB, 70B necesita 64GB\\n- **Parámetros de contexto:** Ajustar `num_ctx` según longitud esperada de inputs\\n- **Temperatura:** 0.3 para tareas técnicas, 0.7 para generación creativa\\n\\n## Preguntas de Profundización\\n\\n- ¿Cómo implementar un sistema de fallback entre múltiples instancias de Ollama?\\n- ¿Qué métricas usar para monitorizar el rendimiento de modelos en producción?\\n- ¿Cómo integrar Ollama con sistemas de CI/CD para testing automatizado?\\n\\n## Conexiones Interdisciplinares\\n\\n**Con Trading:** Modelos locales para análisis de sentimiento de noticias financieras sin enviar datos sensibles a APIs externas\\n\\n**Con Desarrollo:** Integración en IDEs para autocompletado de código y review automatizado\\n\\n**Con IA:** Base para construir agentes especializados que mantengan privacidad de datos",

  "processing_time_seconds": 45.2,

  "tokens_input": 8400,

  "tokens_output": 2100,

  "cost_usd": 0.000000,

  "metadata": {

    "model_tier": "local",

    "fallback_used": false,

    "chunk_strategy": "single_pass",

    "vram_used_gb": 38.2

  }

}

```



### Error Response

```json

{

  "task_id": "proc_20240620_143022_dQw4w9WgXcQ",

  "status": "error",

  "error_code": "MODEL_UNAVAILABLE",

  "error_message": "Preferred model llama3.1:70b is offline and fallback disabled",

  "retry_possible": true,

  "suggested_model": "llama3.1:8b",

  "suggested_action": "retry_with_fallback"

}

```



### Aborted Response

```json

{

  "task_id": "proc_20240620_143022_dQw4w9WgXcQ",

  "status": "aborted",

  "aborted_reason": "user_request",

  "aborted_at": "2024-06-20T14:33:15Z",

  "partial_result": null,

  "processing_time_seconds": 23.1

}

```



## 4. Orchestrator → Obsidian (File System)



### Frontmatter Enriquecido para Obsidian

```yaml

---

title: "Cómo Configurar Ollama para Modelos Locales de IA"

source: "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

source_type: "youtube"

channel: "TechChannel Pro"

published_date: "2024-05-10"

captured_at: "2024-06-20T14:30:22Z"

processed_at: "2024-06-20T14:35:45Z"

model_used: "llama3.1:70b"

profile_used: "Técnico Profundo"

processing_time: 45.2

tokens_processed: 10500

cost_usd: 0.000000

tags: [ia, llm, ollama, tutorial, configuracion]

topic: "IA-y-LLMs"

obsolescence_date: "2024-12-17"

status: "processed"

---

```



### Estructura del Contenido Final

```markdown

# Cómo Configurar Ollama para Modelos Locales de IA



{result_markdown_from_broker}



---

## Metadata del Procesamiento

- **Procesado con:** llama3.1:70b

- **Perfil aplicado:** Técnico Profundo  

- **Tiempo de procesamiento:** 45.2s

- **Archivo fuente:** [[yt_20240620_143022_dQw4w9WgXcQ]]

```



## 5. Broker Internal APIs



### GET /api/v1/models

```json

{

  "local_models": [

    {

      "name": "llama3.1:70b",

      "size_gb": 38.2,

      "status": "available",

      "context_window": 131072,

      "estimated_vram_gb": 42.0,

      "last_used": "2024-06-20T14:30:00Z",

      "performance_tier": "high"

    },

    {

      "name": "llama3.1:8b", 

      "size_gb": 4.7,

      "status": "loaded",

      "context_window": 131072,

      "estimated_vram_gb": 8.0,

      "current_requests": 1,

      "performance_tier": "fast"

    },

    {

      "name": "qwen2.5:72b",

      "size_gb": 41.0,

      "status": "available", 

      "context_window": 32768,

      "estimated_vram_gb": 45.0,

      "specialty": "code_analysis"

    }

  ],

  "external_models": [

    {

      "name": "deepseek-chat",

      "provider": "deepseek",

      "status": "online",

      "cost_per_1k_input": 0.00014,

      "cost_per_1k_output": 0.00028,

      "monthly_usage": 0.12,

      "monthly_budget": 5.00,

      "context_window": 64000

    }

  ],

  "system_status": {

    "vram_used_gb": 42.1,

    "vram_total_gb": 64.0,

    "vram_percentage": 65.8,

    "ollama_status": "online",

    "active_tasks": 1

  }

}

```



### GET /api/v1/queue

```json

{

  "pending": [

    {

      "task_id": "task_001",

      "title": "Python Async Patterns Explained",

      "estimated_tokens": 6500,

      "preferred_model": "llama3.1:8b",

      "queued_at": "2024-06-20T14:32:00Z",

      "priority": 1,

      "estimated_cost": 0.000000

    },

    {

      "task_id": "task_003",

      "title": "Advanced Trading Strategies",

      "estimated_tokens": 12000,

      "preferred_model": "llama3.1:70b",

      "queued_at": "2024-06-20T14:33:15Z",

      "priority": 2,

      "estimated_cost": 0.000000

    }

  ],

  "processing": [

    {

      "task_id": "task_002",

      "title": "Cómo configurar Ollama para Modelos Locales",

      "model_used": "llama3.1:70b",

      "progress_percentage": 68,

      "started_at": "2024-06-20T14:30:00Z",

      "estimated_completion": "2024-06-20T14:35:30Z",

      "tokens_processed": 5712,

      "tokens_estimated": 8400

    }

  ],

  "completed_last_24h": 47,

  "failed_last_24h": 3,

  "average_processing_time_seconds": 52.3,

  "total_cost_today": 0.08

}

```



## 6. Configuration Files Schema



### Orchestrator Config (config.yaml)

```yaml

paths:

  inbox: "%USERPROFILE%/Downloads/YT-Knowledge-Inbox"

  processing: "C:/YT-Pipeline/processing"

  completed: "C:/YT-Pipeline/completed"

  failed: "C:/YT-Pipeline/failed"

  rejected: "C:/YT-Pipeline/rejected"

  obsidian_vault: "C:/ObsidianVault/Knowledge"



broker:

  hostname: "broker-machine.local"

  port: 8080

  timeout_seconds: 180

  retry_attempts: 3

  health_check_interval: 60



processing:

  auto_process: true

  max_concurrent_ingestion: 2

  active_hours:

    start: "09:00"

    end: "22:00"

  check_interval_seconds: 30



topics:

  - name: "IA-y-LLMs"

    folder: "IA-y-LLMs"

    keywords: ["ia", "llm", "gpt", "ollama", "neural", "machine learning", "deep learning"]

    obsolescence_days: 180

    default_profile: "Técnico Profundo"

    auto_create_folder: true

  

  - name: "Desarrollo"

    folder: "Desarrollo"

    keywords: ["python", "javascript", "api", "código", "programming", "docker", "git"]

    obsolescence_days: 365

    default_profile: "Técnico Profundo"

    auto_create_folder: true



  - name: "Trading"

    folder: "Trading" 

    keywords: ["trading", "forex", "btc", "cripto", "bolsa", "inversión", "análisis técnico"]

    obsolescence_days: 365

    default_profile: "Técnico Profundo"

    auto_create_folder: true



profiles:

  - name: "Técnico Profundo"

    system_prompt: "Eres un experto analista de conocimiento técnico. Tu tarea es extraer exhaustivamente todos los conceptos, herramientas, técnicas y datos valiosos de transcripciones de video, organizándolos de manera estructurada para facilitar el aprendizaje y la referencia posterior."

    user_prompt: "Analiza esta transcripción de video de YouTube y extrae TODO el conocimiento valioso:\\n\\nTítulo: {title}\\nCanal: {channel}\\nFecha publicación: {published_date}\\n\\nTranscripción:\\n{transcript}\\n\\nGenera una nota completa en formato Markdown con estructura clara, conceptos técnicos detallados, herramientas mencionadas, y aplicaciones prácticas."

    temperature: 0.3

    max_tokens: 4000

    preferred_model: "llama3.1:70b"



  - name: "Resumen Ejecutivo"

    system_prompt: "Eres un especialista en síntesis de información. Tu objetivo es extraer solo los puntos más importantes y accionables de contenido técnico."

    user_prompt: "Crea un resumen ejecutivo conciso de esta transcripción:\\n\\nTítulo: {title}\\nCanal: {channel}\\n\\nTranscripción:\\n{transcript}\\n\\nIncluye: resumen de 2-3 párrafos, 5 puntos clave máximo, 3 acciones concretas."

    temperature: 0.2

    max_tokens: 2000

    preferred_model: "llama3.1:8b"

```



### Broker Config (broker_config.yaml)

```yaml

server:

  host: "0.0.0.0"

  port: 8080

  workers: 1

  cors_enabled: false

  allowed_origins: []



ollama:

  url: "http://localhost:11434"

  health_check_interval: 30

  model_discovery_interval: 300

  default_keep_alive: "5m"

  max_active_llm_tasks: 1



external_apis:

  deepseek:

    endpoint: "https://api.deepseek.com/chat/completions"

    model: "deepseek-chat"

    api_key: "${DEEPSEEK_API_KEY}"

    monthly_budget: 5.00

    cost_per_1k_input: 0.00014

    cost_per_1k_output: 0.00028

    max_concurrent: 1

    timeout_seconds: 180



processing:

  queue_check_interval: 2

  task_timeout_seconds: 300

  max_retry_attempts: 3

  backoff_strategy: "exponential"



logging:

  level: "INFO"

  file: "logs/broker.log"

  max_size_mb: 100

  backup_count: 5

  structured: true



monitoring:

  vram_alert_threshold: 90

  budget_alert_threshold: 80

  health_check_endpoints: ["/health", "/api/v1/models"]

```



## 7. Error Handling Standards



### Error Codes y Retry Logic

```python

ERROR_CODES = {

    "INVALID_REQUEST": {

        "message": "Request format is invalid",

        "retry": False,

        "http_status": 400

    },

    "MODEL_UNAVAILABLE": {

        "message": "Requested model is not available", 

        "retry": True,

        "fallback_strategy": "auto_select_alternative",

        "max_attempts": 3

    },

    "BUDGET_EXCEEDED": {

        "message": "Monthly budget limit exceeded",

        "retry": False,

        "fallback_strategy": "local_only"

    },

    "TIMEOUT": {

        "message": "Request processing timeout",

        "retry": True,

        "backoff_seconds": [30, 60, 120],

        "max_attempts": 3

    },

    "VRAM_INSUFFICIENT": {

        "message": "Insufficient VRAM for requested model",

        "retry": True,

        "fallback_strategy": "smaller_model"

    },

    "TRANSCRIPTION_MISSING": {

        "message": "No transcription found in source file",

        "retry": False,

        "action": "move_to_failed_folder"

    }

}

```

## 8. Contratos Normativos v1

Esta sección es la fuente de verdad para el MVP y prevalece sobre los ejemplos anteriores.

### 8.1 Captura Markdown genérica

Todo fichero usa UTF-8, frontmatter YAML válido y el siguiente esquema lógico:

```yaml
---
contract_version: "1.0"
capture_id: "source_20260620_143022_identifier"
source_type: "youtube"
title: "Título descriptivo"
captured_at: "2026-06-20T14:30:22Z"
has_transcript: true
source_url: "https://..."          # opcional para fuentes genéricas
published_date: "2026-05-10"      # opcional
transcript_language: "es"         # opcional
status: "pending"

# Solo source_type=youtube
video_id: "dQw4w9WgXcQ"
channel: "Canal"
channel_url: "https://..."
duration_seconds: 1725
extraction_method: "schema_jsonld"
transcript_source: "manual"       # manual | automatic | null
plugin_version: "1.0.0"
---

# Título descriptivo

## Transcripción

[00:00:00] Texto de la fuente...
```

Campos obligatorios para todas las fuentes: `contract_version`, `capture_id`, `source_type`, `title`, `captured_at`, `has_transcript` y `status`. Si `has_transcript` es verdadero, la sección `## Transcripción` debe contener texto. Los campos desconocidos se conservan como metadata adicional, pero no se reenvían al Broker salvo allowlist explícita.

Reglas:

- Fechas y horas usan ISO 8601; timestamps con zona y fechas simples en `YYYY-MM-DD`.
- `capture_id` admite `[A-Za-z0-9._-]`, máximo 128 caracteres, y es la clave de idempotencia.
- El fichero completo no excede 20 MiB en el MVP.
- YAML se analiza con carga segura. No se ejecutan tags, HTML, scripts ni instrucciones incluidas en el contenido.
- `status` de entrada siempre es `pending`.

### 8.2 Crear tarea en el Broker

`POST /api/v1/tasks`

```json
{
  "idempotency_key": "yt_20260620_143022_dQw4w9WgXcQ:1:single",
  "request_id": "proc_20260620_143022_dQw4w9WgXcQ_r1_single",
  "content": {
    "prompt": "<system_instructions>Eres un analista...</system_instructions>\n<user_request>Analiza el texto ya preparado...</user_request>",
    "attachments": [],
    "metadata": {"workflow_id": "wf_...", "step_id": "single"}
  },
  "output": {"format": "markdown", "json_schema": null, "language": "es"},
  "generation": {"temperature": 0.3, "max_output_tokens": 4000},
  "model_requirements": {
    "preferred_model": "llama3.1:70b",
    "fallback_allowed": true,
    "cloud_allowed": false,
    "allowed_providers": ["ollama"],
    "max_cost_usd": 0.05
  },
  "execution": {
    "strategy": "single",
    "preset": "fast",
    "scheduling": "adaptive",
    "max_proposers": 1,
    "max_judges": 0,
    "max_rounds": 1,
    "timeout_seconds": 600,
    "early_stop": true,
    "selection": {"mode": "auto", "proposer_count": 1, "allow_substitution": true}
  },
  "risk": {"data_classification": "local_only", "human_review_required": false},
  "priority": 100
}
```

El Orchestrator renderiza el prompt final antes del POST. El Broker no conoce placeholders, fuentes, chunks, afirmaciones, Obsidian ni el objetivo del workflow. `content.metadata` solo contiene correlación allowlist y se trata como opaca.

El contrato de embeddings se congelará antes de la fase que los utilice; no se simula mediante el formato Markdown.

Respuesta `202 Accepted`:

```json
{
  "task_id": "task_72b7196358d74343b92033a98a19eb8a",
  "status": "queued",
  "execution_strategy": "single",
  "execution_preset": "fast",
  "selection_mode": "auto",
  "status_url": "/api/v1/tasks/task_72b7196358d74343b92033a98a19eb8a",
  "cancel_url": "/api/v1/tasks/task_72b7196358d74343b92033a98a19eb8a"
}
```

La misma `idempotency_key` y hash devuelve la tarea existente con `200`, incluso tras reinicio; la misma clave con contenido diferente devuelve `409`.

### 8.3 Consultar y cancelar tareas

`GET /api/v1/tasks/{task_id}` devuelve:

```json
{
  "task_id": "task_...",
  "request_id": "proc_...",
  "status": "generating",
  "created_at": "2026-06-20T14:30:22Z",
  "updated_at": "2026-06-20T14:30:25Z",
  "execution_strategy": "single",
  "execution_preset": "fast",
  "selection_mode": "auto",
  "progress": {"phase": "generating", "invocations_completed": 0, "invocations_total": 1},
  "result": null,
  "error": null
}
```

Estados: `queued`, fases activas `routing/planning/resource_planning/chunking/generating/proposing/evaluating/debating/synthesizing/verifying`, y terminales `completed/failed/cancelled`.

En `completed`, `result.result_markdown` contiene la salida y puede incluir uso, modelos, consenso y scheduling. El Orchestrator la normaliza internamente como `assistant_content` y valida el Markdown antes de publicar. En `failed`, `error` contiene al menos `code` y, cuando proceda, `message` y `retryable`. `DELETE` es idempotente.

### 8.4 Cola, modelos y salud

- `GET /api/v1/queue`: listas ordenadas `pending`, `active` y `terminal`.
- Invariante inicial: `active` contiene cero o un workflow Broker; una estrategia de consenso puede tener invocaciones internas.
- `PATCH /api/v1/queue`: `{ "task_ids": ["task_2", "task_1"] }`; debe contener exactamente todas las tareas pendientes actuales o devuelve `409`.
- `GET /api/v1/models`: modelos Ollama y proveedores externos configurados, con `name`, `provider`, `status`, `context_window` cuando se conozca y capacidades declaradas.
- `GET /api/v1/usage`: consumo por proveedor y mes, coste confirmado y reservado.
- `GET /health/live`: `200` si proceso y event loop están vivos.
- `GET /health/ready`: `200` si SQLite y dispatcher pueden aceptar tareas; `503` en caso contrario.
- `GET /health`: estado `healthy | degraded | unavailable` y detalle de SQLite, Ollama, VRAM, disco y proveedores con `checked_at`, latencia y error sanitizado.

### 8.5 Códigos HTTP y errores

- `400 INVALID_REQUEST`, `404 TASK_NOT_FOUND`, `409 IDEMPOTENCY_CONFLICT` o `QUEUE_CONFLICT`.
- `413 CONTENT_TOO_LARGE`, `422 CONTRACT_VALIDATION_FAILED` o `TEMPLATE_ERROR`, `429 QUEUE_FULL`.
- Errores de modelo/proveedor ocurridos después de aceptar una tarea se consultan en el recurso de tarea, no cambian retroactivamente el `202`.
- `MODEL_UNAVAILABLE`, `BUDGET_EXCEEDED`, `TIMEOUT`, `PROVIDER_UNAVAILABLE`, `VRAM_INSUFFICIENT`, `CANCELLED` y `INTERNAL_ERROR` son códigos terminales del worker.

### 8.6 Persistencia y transiciones

- Orchestrator y Broker usan SQLite separado, modo WAL, claves foráneas y transacciones para cada transición.
- El Orchestrator conserva `capture_id`, `revision`, rutas de origen/nota, `task_id`, estado, timestamps y último error.
- El Broker conserva request normalizado, hash, posición, intento, estado, proveedor/modelo, uso y eventos. Las API keys nunca se persisten en estas tablas.
- La ingestión usa `staging`, hash SHA-256, commit SQLite y `os.replace` según el protocolo write-then-move. Las publicaciones Markdown usan igualmente temporal + rename atómico y estado recuperable.

### 8.7 Semántica de despacho serial

1. El Orchestrator puede realizar varios `POST /api/v1/tasks` sin esperar a que las tareas anteriores terminen.
2. Cada `POST` válido devuelve rápidamente `202` y la tarea queda durablemente `queued`.
3. En el contrato v1/baseline `single`, el Broker posee un único slot global. La fase 5 prevista mantendrá un solo workflow activo, pero permitirá invocaciones internas adaptativas dentro de una tarea `mixture_of_agents`.
4. El dispatcher toma la primera tarea pendiente solo cuando no existe otro workflow activo y cambia su estado dentro de una transacción.
5. En `single`, cada tarea representa exactamente una inferencia. En la futura estrategia `mixture_of_agents`, una tarea podrá representar un consenso técnico interno. En ambos casos, chunks, dependencias, pasos y síntesis del workflow de conocimiento pertenecen al Orchestrator.
6. El workflow activo se libera únicamente al persistir su estado terminal o al agotar el timeout aplicable.
7. Una tarea lenta mantiene ocupado el workflow global y las posteriores continúan en `queued`. Solo sus invocaciones internas pueden solaparse cuando el planificador del Broker lo autoriza.
8. El dashboard, las consultas de estado, la aceptación de nuevas tareas y las cancelaciones permanecen operativos mientras el slot está ocupado.

### 8.8 Validación inmediata en fronteras

- **Plugin → Orchestrator:** el Plugin valida antes de descargar y el Orchestrator vuelve a validar antes de staging. La doble validación es deliberada.
- **Orchestrator → Broker:** el Orchestrator valida el request antes del POST y el Broker lo valida de nuevo en el endpoint antes de SQLite.
- **Broker → Orchestrator:** el Orchestrator valida las respuestas `202`, estados, resultados y errores antes de cambiar el estado local.
- La validación debe comprobar versión, campos obligatorios, tipos, enums, límites, formatos de fecha, placeholders y relaciones condicionales.
- Un objeto inválido no se corrige implícitamente ni se procesa parcialmente. Se devuelve o registra `CONTRACT_VALIDATION_FAILED` con `boundary`, `field`, `reason` y `contract_version`.
- Los ficheros inválidos se conservan en `failed/contracts`; los requests inválidos no crean filas ni consumen posiciones de cola.

### 8.9 Estados de staging de archivos

- `STAGED`: copia temporal sincronizada y fila SQLite confirmada; movimiento a processing pendiente.
- `PENDING`: fichero confirmado en processing y preparado para construir la tarea.
- Cada fila conserva `source_path`, `staging_path`, `processing_path`, `sha256` y `contract_version`.
- La recuperación debe aceptar tanto “SQLite confirmado, fichero aún en staging” como “fichero ya en processing, estado aún STAGED”. Ambas situaciones se completan idempotentemente.

### 8.10 Contratos internos de mantenimiento semántico

Estos objetos pertenecen exclusivamente al Orchestrator y nunca forman parte del dominio del Broker.

```yaml
knowledge_claim:
  claim_id: "ollama-context-window"
  knowledge_id: "ollama-configuration"
  note_path: "IA-y-LLMs/Ollama.md"
  statement: "El modelo X admite 8192 tokens"
  claim_type: "technical_limit"
  entities: ["Ollama", "modelo X"]
  volatility: "high"
  valid_as_of: "2026-01-10"
  source_ids: ["video_123"]
  source_spans: ["00:12:10-00:12:42"]
  manual_lock: false
  status: "verified"
```

```yaml
update_candidate:
  candidate_id: "upd_123"
  claim_id: "ollama-context-window"
  new_source_ids: ["video_456"]
  relationship: "supersedes"  # supports | extends | contradicts | supersedes | unrelated | uncertain
  confidence: 0.94
  impact: "high"
  evidence_spans: ["video_456:00:03:10-00:03:44"]
  proposed_operations: []
  status: "awaiting_user_review"
```

Toda propuesta debe citar fuentes y spans existentes en el repositorio local. El conocimiento interno del LLM no es evidencia. `manual_lock: true` impide sustitución automática y obliga a conservar el texto o solicitar una decisión explícita.

### 8.11 Contrato Broker v2 y base futura para Multitasking_LLM

El contrato v2 está implementado para `single` y constituye la base de la futura fase 5.

AI Broker usa `idempotency_key`, `request_id`, `content`, `output`, `generation`, `model_requirements`, `execution`, `risk` y `priority`; genera su propio `task_id`; publica fases detalladas; termina en `completed`, `failed` o `cancelled`; y entrega `result_markdown` con metadata técnica. El Orchestrator adapta y valida este esquema y conserva por separado el ID local y el ID Broker.

El contrato incluye:

- clave idempotente y hash canónico con semántica `200 existente`/`409 conflicto`;
- correlación separada entre ID local, `request_id` y `task_id` del Broker;
- política `single | mixture_of_agents`, preset, selección y límites;
- clasificación de datos, autorización cloud, allowlist de proveedores y coste máximo;
- fases, progreso por unidades y estados terminales;
- resultado `result_markdown` o JSON/embedding según el paso;
- consenso, scheduling, uso, modelos, advertencias y desacuerdos;
- errores tipados de quórum, presupuesto, contexto, privacidad y capacidad.

`single` seguirá siendo el valor predeterminado. Los chunks y embeddings no usarán consenso inicialmente. La confianza de consenso nunca se tratará como evidencia factual. El análisis completo está en `docs/Study_Multitasking_LLM.md`.
