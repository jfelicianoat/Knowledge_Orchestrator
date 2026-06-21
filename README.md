# Knowledge Orchestrator — Desktop Pipeline

Aplicación de escritorio que orquesta el pipeline de captura → procesamiento → publicación de contenido de YouTube (y fuentes genéricas) hacia Obsidian, utilizando LLMs locales y externos.

## Arquitectura del Ecosistema

```
[YT Capture Agent] ──► Knowledge Orchestrator ──► [AI Broker] ──► Ollama (local)
  (Chrome Extension)           │                      │              ├── llama3.1:70b
        ↵                      │                     HTTP            ├── llama3.1:8b
  Archivos .md                 │                     REST             └── qwen2.5:72b
        ↵                      │                      │
  Downloads/                   ▼                      ├──► DeepSeek API
  YT-Knowledge-Inbox     [Obsidian Vault]             │
                                                  └──► Dashboard Web
                                                      (FastAPI + HTMX)
```

### Proyectos Relacionados

| Proyecto | Descripción | Repositorio |
|----------|-------------|-------------|
| **YT Capture Agent** | Extensión Chrome que captura metadata y transcripciones de YouTube, generando archivos `.md` estructurados | [jfelicianoat/YT_Capture_Agent](https://github.com/jfelicianoat/YT_Capture_Agent) |
| **AI Broker** | Gateway de procesamiento LLM con cola serial, enrutamiento inteligente y dashboard web | [jfelicianoat/AI_Broker](https://github.com/jfelicianoat/AI_Broker) |
| **Knowledge Orchestrator** | Orquestador de escritorio que conecta la captura con el procesamiento y la publicación en Obsidian **(este proyecto)** | [jfelicianoat/Knowledge_Orchestrator](https://github.com/jfelicianoat/Knowledge_Orchestrator) |

## Stack

| Componente | Tecnología |
|------------|------------|
| UI Framework | CustomTkinter (tema oscuro) |
| File Monitoring | watchdog |
| HTTP Client | httpx (asíncrono) |
| Gráficos | matplotlib |
| Configuración | PyYAML |
| Persistencia | SQLite + WAL |

## Funcionalidades clave

- **File Watcher inteligente**: monitoriza la carpeta inbox, valida frontmatter YAML y reclama archivos estables
- **Pipeline visual animado**: cola con estados Pendiente → Procesando → Completado/Error con indicadores visuales
- **Dashboard en tiempo real**: métricas diarias, gráficos de actividad, monitorización de modelos del Broker
- **Gestión de temas**: auto-detección por keywords, carpetas dinámicas en Obsidian, perfiles por tema
- **Sistema de revisión**: aceptar/rechazar notas, reprocesar desde fuente original, historial completo
- **Comunicación resiliente**: reintentos con backoff exponencial, recuperación automática tras reinicio

## UI (Ventana Única con Menú Lateral)

```
┌──────────────────────────────────────────────────────────────┐
│  Knowledge Orchestrator                          [─][□][✕]   │
├──────────────┬───────────────────────────────────────────────┤
│  📊 Dashboard│  [Contenido de la pestaña activa]             │
│  🔄 Cola     │                                               │
│  📝 Revisión │                                               │
│  🗂️ Temas    │                                               │
│  ⚙️ Config   │                                               │
├──────────────┤                                               │
│ 🟢 Broker OK │                                               │
│ 3 pendientes │                                               │
└──────────────┴───────────────────────────────────────────────┘
```

## Flujo de datos

1. El **YT Capture Agent** descarga archivos `.md` con frontmatter y transcripción en `Downloads/YT-Knowledge-Inbox`
2. El **Knowledge Orchestrator** detecta el archivo via watchdog, valida el contrato v1 y lo reclama
3. Determina el tema por keywords y construye el payload con el perfil correspondiente
4. Envía la tarea al **AI Broker** via `POST /api/v1/tasks` (recibe `202 Accepted`)
5. Consulta periódicamente el estado hasta obtener el resultado
6. En éxito, escribe la nota procesada en la carpeta temática del vault de Obsidian
7. El origen se mueve a `completed`; los errores van a `failed` con logs detallados

## Estados de procesamiento

```
PENDING → SUBMITTING → QUEUED → PROCESSING → COMPLETED → (publicado en Obsidian)
                                    ↓
                              FAILED / REJECTED / CANCELLED
```

## Contrato normativo del MVP

- UI renderiza estado y envía comandos; no accede directamente a HTTP, SQLite ni filesystem
- Servicios coordinan ingestión, clasificación, envío, publicación, rechazo y reprocesado
- Repositorios encapsulan SQLite y movimientos de archivos
- Worker posee el bucle `asyncio`, reintentos, polling y cancelación
- Comunicación con Broker via HTTP en LAN privada, sin autenticación (MVP)
- Base SQLite en `C:/YT-Pipeline/state/orchestrator.db` con modo WAL

## Licencia

MIT
