# Knowledge Orchestrator — Desktop Pipeline

Orquestador de escritorio que conecta la captura de contenido con el procesamiento por LLMs y la publicación en Obsidian. Orquesta workflows de conocimiento — chunking, síntesis, extracción de afirmaciones y comparación semántica — mientras que el AI Broker ejecuta una estrategia técnica `single` o, en una fase futura, `mixture_of_agents`/Multitasking_LLM.

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
| **AI Broker** | Gateway con cola durable, enrutamiento y ejecución opcional de consenso multi-LLM. Puede coordinar invocaciones técnicas internas, pero no contiene lógica de conocimiento ni workflows de Obsidian. | [jfelicianoat/AI_Broker](https://github.com/jfelicianoat/AI_Broker) |
| **Knowledge Orchestrator** | Orquestador que valida entradas, decide temas, construye y encadena inferencias, interpreta respuestas, mantiene claims/diffs/versiones y publica en Obsidian **(este proyecto)** | [jfelicianoat/Knowledge_Orchestrator](https://github.com/jfelicianoat/Knowledge_Orchestrator) |

## Stack

| Componente | Tecnología |
|------------|------------|
| UI Framework | Tkinter/ttk |
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
- El Broker recibe prompts finales, los encola, selecciona modelos/proveedores y devuelve una respuesta técnica. No conoce fuentes, chunks, Obsidian ni el workflow de conocimiento
- En el modo actual `single`, una tarea equivale a una inferencia. La fase 5 añadirá `mixture_of_agents`, donde una tarea sigue siendo una unidad opaca para el Orchestrator pero puede contener invocaciones internas acotadas
- `content.metadata` contiene únicamente correlación allowlist; el Broker no la interpreta
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

La UI inicial de fase 7 ya está implementada con Dashboard, Cola, Revisión, Temas y Configuración. El mantenimiento semántico durable está implementado en la fase 6.

La fase 2 añade:

- fuentes genéricas con origen durable `PLUGIN_CAPTURE`, `USER_FILE` u `OBSIDIAN_NOTE`;
- exclusión contractual de RSS, documentación vigilada, conectores automáticos y búsqueda web autónoma;
- clasificación ordenada por keywords y fallback reservado `_inbox`;
- carpetas seguras creadas automáticamente bajo el vault;
- vigencia por tema sin actualización factual automática;
- perfiles editables y versionados con prompts normal, chunk y síntesis;
- enriquecimiento recuperable de capturas `PENDING` tras reinicio.

La especificación operativa está en [`docs/Phase_2_Domain.md`](docs/Phase_2_Domain.md). La edición visual de temas y perfiles queda reservada para la fase 7; Broker y renderizado efectivo de prompts comienzan en la fase 3.

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
  ui/              # puente thread-safe, snapshots y ventana Tk
  migrations/      # esquema versionado
tests/
```

### Fase 3 — Frontera con el Broker

La fase 3 implementa el cliente HTTP asíncrono y la validación inmediata del contrato Broker v2, con identificadores locales separados de los `task_id` asignados por el Broker. Incluye workflows durables simples o por chunks, síntesis con dependencias, creación `202`, replay idempotente `200`, detección de conflictos `409`, dispatcher y poller independientes, reintentos transitorios, recuperación tras reinicio y descubrimiento periódico de modelos.

El dispatcher envía todos los chunks disponibles sin esperar resultados. En el baseline `single`, el Broker procesa una inferencia a la vez. La futura opción Multitasking_LLM mantendrá un solo workflow Broker activo, aunque podrá ejecutar invocaciones internas mediante planificación adaptativa. El worker de red está separado del watcher y del hilo principal.

Véase [`docs/Phase_3_Broker.md`](docs/Phase_3_Broker.md). Además de los dobles de prueba, se verificó el proceso FastAPI real del AI Broker desde alta y replay idempotente hasta publicación final.

### Fase 4 — Publicación y revisión

La fase 4 publica el resultado final en Obsidian mediante intención SQLite, temporal sincronizado, `os.replace` y verificación SHA-256. La captura solo pasa a `COMPLETED` después de guardar la nota y archivar la fuente. El arranque recupera publicaciones incompletas.

El rechazo retira nota y fuente a `rejected` sin destruirlas. El reprocesado copia la evidencia conservada a `processing` y crea una revisión nueva con identificadores idempotentes distintos. Véase [`docs/Phase_4_Publication.md`](docs/Phase_4_Publication.md).

### Fase 5 — Multitasking_LLM

La integración opcional con `mixture_of_agents/fast` está implementada mediante una política versionada por perfil y paso. `single` sigue siendo el valor predeterminado; los chunks permanecen en `single` y el consenso se reserva para síntesis o pasos `single` habilitados expresamente.

La integración incluye validación de metadata de consenso, progreso durable y fallback `single` restringido a fallos de quorum/capacidad. AI Broker ya dispone de providers reales y catálogo; la activación por defecto sigue esperando el benchmark representativo. Véanse [`docs/Phase_5_Multitasking.md`](docs/Phase_5_Multitasking.md) y [`docs/Study_Multitasking_LLM.md`](docs/Study_Multitasking_LLM.md).

### Fase 6 — Mantenimiento semántico

Cada nota publicada crea un job durable de extracción de claims. El Orchestrator construye prompts `local_only` con JSON Schema, valida que las citas coincidan exactamente con spans locales y recupera candidatos por tema, entidades, FTS5 y embeddings opcionales.

Las comparaciones generan relación, confianza, impacto, patch y diff. Ningún cambio se aplica automáticamente: `manual_lock` bloquea la propuesta y los demás candidatos quedan `PENDING_REVIEW` hasta aprobación humana. La aprobación conserva la revisión anterior y usa escritura sincronizada más reemplazo atómico recuperable.

Véase [`docs/Phase_6_Semantic_Maintenance.md`](docs/Phase_6_Semantic_Maintenance.md).

### Fase 7 — Cola visual y revisión

La interfaz se abre con:

```powershell
$env:PYTHONPATH='src'
python -m knowledge_orchestrator.app --ui
```

Incluye Dashboard, Cola, Revisión, Temas y Configuración. La UI refresca cada 2 segundos desde snapshots SQLite de solo lectura, drena eventos del worker únicamente en el hilo principal y muestra posición, estado, fase, modelo, tiempo transcurrido e intentos sin inventar porcentajes.

La pestaña Revisión muestra candidatos semánticos `PENDING_REVIEW` con diff y rationale, y permite aprobar o rechazar usando los servicios atómicos existentes. Véase [`docs/Phase_7_UI.md`](docs/Phase_7_UI.md).

### Fase 8 — Operación y empaquetado

Operación básica:

```powershell
$env:PYTHONPATH='src'
python -m knowledge_orchestrator.app --backup
python -m knowledge_orchestrator.app --diagnostics C:\tmp\ko-diagnostics.zip
```

El backup usa la API consistente de SQLite y se guarda en `backups/`. El diagnóstico genera un ZIP sin base de datos ni contenido de notas, con contadores, entorno, configuración saneada y cola de logs redacted.

Build Windows:

```powershell
.\scripts\build_windows.ps1 -Clean
```

Véase [`docs/Phase_8_Operations.md`](docs/Phase_8_Operations.md).

## Licencia

MIT
