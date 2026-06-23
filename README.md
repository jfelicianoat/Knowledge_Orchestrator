# Knowledge Orchestrator — Desktop Pipeline

Orquestador de escritorio que conecta la captura de contenido con el procesamiento por LLMs y la publicación en Obsidian. Orquesta workflows completos de inferencia — chunking, síntesis, extracción de afirmaciones y comparación semántica — mientras que el AI Broker se limita a ejecutar inferencias individuales.

## Arquitectura del Ecosistema

```
[YT Capture Agent] ──► Knowledge Orchestrator ──► [AI Broker] ──► Ollama (local)
  (Chrome Extension)                │                    │            ├── llama3.1:70b
         ↵                          │                  HTTP           ├── llama3.1:8b
   Archivos .md              Workflow completo        REST            └── qwen2.5:72b
         ↵                   (chunks, síntesis,         │
   Downloads/                 claims, diffs)            ├──► DeepSeek API
   YT-Knowledge-Inbox               ▼                   │
                            [Obsidian Vault]         Inferencias
                            + knowledge_claims      individuales
                            + versiones previas
```

### Proyectos Relacionados

| Proyecto | Descripción | Repositorio |
|----------|-------------|-------------|
| **YT Capture Agent** | Extensión Chrome que captura metadata y transcripciones de YouTube, generando archivos `.md` estructurados | [jfelicianoat/YT_Capture_Agent](https://github.com/jfelicianoat/YT_Capture_Agent) |
| **AI Broker** | Gateway de inferencia LLM con cola serial, enrutamiento de modelos y dashboard web. No contiene lógica de conocimiento ni orquesta workflows. | [jfelicianoat/AI_Broker](https://github.com/jfelicianoat/AI_Broker) |
| **Knowledge Orchestrator** | Orquestador que valida entradas, decide temas, construye y encadena inferencias, interpreta respuestas, mantiene claims/diffs/versiones y publica en Obsidian **(este proyecto)** | [jfelicianoat/Knowledge_Orchestrator](https://github.com/jfelicianoat/Knowledge_Orchestrator) |

## Stack

| Componente | Tecnología |
|------------|------------|
| UI Framework | CustomTkinter (tema oscuro) |
| File Monitoring | watchdog |
| HTTP Client | httpx (asíncrono) |
| Gráficos | matplotlib |
| Configuración | PyYAML |
| Persistencia | SQLite + WAL + FTS5 |

## Funcionalidades clave

- **File Watcher inteligente**: verifica estabilidad, reintenta locks y valida contrato v1 antes de staging
- **Ingestión recuperable**: staging, SHA-256, commit SQLite y movimiento atómico a processing
- **Orquestación completa de inferencias**: el Orchestrator renderiza prompts, resuelve placeholders, divide en chunks por límites naturales, encadena tareas Broker para cada chunk + síntesis, y valida cada respuesta
- **Mantenimiento semántico**: indexa afirmaciones (`knowledge_claims`) con entidades, volatilidad y fuentes; compara nuevas evidencias contra notas existentes (supports/contradicts/supersedes); genera diff y propuestas con confianza e impacto; requiere aprobación humana antes de sobrescribir
- **Pipeline visual animado**: cola con posición, fase, tiempo y salud del Broker
- **Dashboard en tiempo real**: métricas diarias, gráficos de actividad, monitorización de modelos
- **Gestión de temas**: auto-detección por keywords, carpetas dinámicas en Obsidian, perfiles editables por tema
- **Sistema de revisión**: aceptar/rechazar notas, reprocesar desde original, revisión de candidatos de actualización semántica
- **Recuperación al arranque**: reconcilia SQLite con filesystem, reanuda tareas sin duplicar

## UI (Ventana Única con Menú Lateral)

```
┌──────────────────────────────────────────────────────────────┐
│  Knowledge Orchestrator                          [─][□][✕]   │
├──────────────┬───────────────────────────────────────────────┤
│  📊 Dashboard│  [Contenido de la pestaña activa]             │
│  🔄 Cola     │                                               │
│  📝 Revisión │  (notas + candidatos de actualización)        │
│  🗂️ Temas    │                                               │
│  ⚙️ Config   │                                               │
├──────────────┤                                               │
│ 🟢 Broker OK │                                               │
│ 3 pendientes │                                               │
└──────────────┴───────────────────────────────────────────────┘
```

## Flujo de datos

1. El **YT Capture Agent** (o fuente externa) deposita un `.md` con frontmatter v1 y transcripción en `Downloads/YT-Knowledge-Inbox`
2. El **Orchestrator** espera estabilidad (tamaño/mtime sin cambios por 1s), valida el contrato v1, copia a staging con SHA-256 y registra en SQLite
3. Tras el commit, mueve atómicamente a `processing`
4. Determina tema por keywords y construye prompts con el perfil correspondiente
5. Si el contenido excede el contexto, divide en chunks por límites naturales; envía una tarea Broker por chunk
6. Valida cada respuesta parcial y, si corresponde, envía una tarea de síntesis al Broker
7. Para mantenimiento semántico: extrae afirmaciones de la fuente, las compara contra claims existentes (vía FTS5 + embeddings opcionales), genera propuestas de actualización con evidencia y diff
8. En éxito de publicación, escribe la nota en la carpeta temática de Obsidian y mueve el origen a `completed`
9. Las propuestas semánticas requieren aprobación explícita del usuario antes de modificar notas existentes

## Estados de procesamiento

```
STAGED → PENDING → SUBMITTING → QUEUED → PROCESSING → COMPLETED → (publicado en Obsidian)
                                    ↓
                              FAILED / REJECTED / CANCELLED
```

## Contrato normativo del MVP

- UI renderiza estado y envía comandos; no accede directamente a HTTP, SQLite ni filesystem
- El Orchestrator es el único responsable de construir prompts, resolver placeholders, decidir chunking, encadenar inferencias, interpretar respuestas y proponer actualizaciones semánticas
- El Broker recibe inferencias completas, las encola, selecciona modelo/proveedor y devuelve la respuesta técnica. No conoce el dominio ni el workflow
- Cada tarea Broker representa exactamente una inferencia (chat o embedding). Workflows multi-paso usan tareas independientes encadenadas por el Orchestrator
- `client_context` opaco para correlación: el Broker lo devuelve sin interpretarlo
- Solo se usan fuentes introducidas por el usuario (videos capturados, documentos depositados, notas existentes). Sin RSS, vigilancia de documentación ni búsqueda web autónoma
- Toda propuesta de actualización semántica debe citar evidencia local con `source_id` y span. El conocimiento interno del LLM no es evidencia
- `manual_lock: true` en un claim impide su sustitución automática
- Comunicación con Broker via HTTP en LAN privada, sin autenticación (MVP)
- Base SQLite en `C:/YT-Pipeline/state/orchestrator.db` con modo WAL
- Integridad mediante estados durables y operaciones idempotentes; no existe transacción única SQLite+NTFS

## Desarrollo

La fase 1 implementa la frontera de ingesta y persistencia. Incluye:

- validación segura del contrato Markdown v1 y límite de 20 MiB;
- tres observaciones consecutivas de tamaño/mtime;
- apertura con reintentos y backoff de 1, 2 y 4 segundos;
- SQLite en modo WAL con migraciones para capturas, tareas, eventos, notas, temas y perfiles;
- copia sincronizada a `staging`, SHA-256, commit `STAGED`, `os.replace` y transición `PENDING`;
- recuperación de caídas antes y después de cada transición durable;
- cuarentena de contratos, transcripciones ausentes y duplicados con sidecar JSON;
- worker de ingesta separado y puente de eventos que reserva Tk para el hilo principal.
- vigilancia continua con `watchdog` y rescan periódico de seguridad;
- apagado cancelable sin borrar ficheros que aún estén esperando estabilidad;
- cuarentena recuperable mediante intención durable, movimiento y sidecar.

El mantenimiento semántico y la UI completa pertenecen a fases posteriores.

La fase 2 añade:

- fuentes genéricas con origen durable `PLUGIN_CAPTURE`, `USER_FILE` u `OBSIDIAN_NOTE`;
- exclusión contractual de RSS, documentación vigilada, conectores automáticos y búsqueda web autónoma;
- clasificación ordenada por keywords y fallback reservado `_inbox`;
- carpetas seguras creadas automáticamente bajo el vault;
- vigencia por tema sin actualización factual automática;
- perfiles editables y versionados con prompts normal, chunk y síntesis;
- enriquecimiento recuperable de capturas `PENDING` tras reinicio.

La especificación operativa está en [`docs/Phase_2_Domain.md`](docs/Phase_2_Domain.md). La edición visual de temas y perfiles sigue reservada para la fase 6; Broker y renderizado efectivo de prompts comienzan en la fase 3.

### Preparación

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

### Pruebas

```powershell
$env:PYTHONPATH = "src"
python -B -m unittest discover -s tests -v
```

### Recuperación e ingesta inicial

```powershell
knowledge-orchestrator
```

El comando crea las carpetas predeterminadas, aplica migraciones, reconcilia estados incompletos, ingiere los `.md` existentes y permanece vigilando `%USERPROFILE%/Downloads/YT-Knowledge-Inbox`. Se detiene con `Ctrl+C`.

Para ejecutar únicamente recuperación + ingesta y terminar:

```powershell
knowledge-orchestrator --once
```

Para probar sin escribir en `C:/YT-Pipeline`:

```powershell
knowledge-orchestrator --once --root "$env:TEMP\knowledge-orchestrator-test"
```

Un fichero que siga bloqueado tras los reintentos queda en el inbox y no se reenvía indefinidamente mientras tamaño y `mtime` no cambien. La futura UI invocará el reintento explícito expuesto por el worker.

### Estructura implementada

```text
src/knowledge_orchestrator/
  domain/          # contrato, estados y errores
  repositories/    # SQLite y transiciones durables
  services/        # estabilidad, ingesta y recuperación
  worker/          # ejecución fuera del hilo de UI
  ui/              # puente thread-safe; widgets en fase 6
  migrations/      # esquema versionado
tests/
```

### Fase 3 — Frontera con el Broker

La fase 3 implementa el cliente HTTP asíncrono, validación v1 inmediata, workflows durables simples o por chunks, síntesis con dependencias, aceptación durable `202`, dispatcher y poller independientes, reintentos transitorios, recuperación idempotente y descubrimiento periódico de modelos.

El dispatcher envía todos los chunks disponibles sin esperar a que termine la primera inferencia. Las llamadas de envío se realizan secuencialmente; el Broker mantiene la responsabilidad de ejecutar una sola tarea LLM a la vez. El worker de red está separado del watcher de archivos y del hilo principal.

Véase [`docs/Phase_3_Broker.md`](docs/Phase_3_Broker.md). Las pruebas usan un Broker simulado; la prueba contra el Broker real requiere que dicho servicio esté desplegado y accesible.

### Fase 4 — Publicación y revisión

La fase 4 publica el resultado final en Obsidian mediante intención SQLite, temporal sincronizado, `os.replace` y verificación SHA-256. La captura solo pasa a `COMPLETED` después de guardar la nota y archivar la fuente. El arranque recupera publicaciones incompletas.

El rechazo retira nota y fuente a `rejected` sin destruirlas. El reprocesado copia la evidencia conservada a `processing` y crea una revisión nueva con identificadores idempotentes distintos. Véase [`docs/Phase_4_Publication.md`](docs/Phase_4_Publication.md).

## Licencia

MIT
