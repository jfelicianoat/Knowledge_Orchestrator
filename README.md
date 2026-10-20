# Knowledge Orchestrator — Desktop Pipeline

Orquestador de escritorio que conecta la captura de contenido con el procesamiento por LLMs y la publicación en Obsidian. Orquesta workflows de conocimiento —chunking, síntesis, extracción de afirmaciones y comparación semántica— mientras AI Broker ejecuta la estrategia técnica. El validador acepta el contrato aditivo 2.11, con juicios System-1 opcionales y conserva compatibilidad con 2.8 y 2.9; el aviso de versión compara ya contra un mínimo numérico, no contra una cadena exacta (ver [`docs/CURRENT_STATE.md`](docs/CURRENT_STATE.md)).

La configuración y las demostraciones de reranking y filtrado de transcripciones están en
[System 1](docs/System1_Integration.md), con [evidencia de verificación](docs/System1_Acceptance_20261003.md).

## Arquitectura del Ecosistema

La evolución de conocimiento incluye entidades, vigencia e histórico y una **API local v1
autenticada** para documentos, claims, búsqueda, consultas fundamentadas e ingesta.
Consultar [configuración y contratos de Knowledge API](docs/Knowledge_API.md) y
[plan de fases 9–14](docs/Knowledge_Lifecycle_Plan.md). La monitorización y la gobernanza
ampliada siguen en desarrollo; los checkpoints distinguen pruebas locales y pruebas externas pendientes.

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
| **YT Capture Plugin** | Extensión Chrome/Edge que captura metadata y transcripciones de YouTube y genera Markdown contractual v1 | [proyecto local](../YT_Capture_Plugin) |
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
- **Pipeline visual animado**: cola con posición, fase, tiempo, salud del Broker, espera de memoria explicada y cancelación
- **Dashboard en tiempo real**: métricas diarias, gráficos de actividad, monitorización de modelos
- **Gestión de temas**: auto-detección por keywords, carpetas dinámicas en Obsidian, perfiles editables por tema
- **Sistema de revisión**: aceptar/rechazar notas, reprocesar desde original, revisión de candidatos de actualización semántica
- **Recuperación al arranque**: reconcilia SQLite con filesystem, reanuda tareas sin duplicar

## UI (Centro de operaciones)

```
┌──────────────────┬─────────────────────────────┬───────────────────────────┐
│ KO  v0.4.1       │ Documentos                  │ Documento seleccionado    │
│ [+ Importar]     │ [En proceso 2][Atención 2]… │ ✓──✓──○──○──○  (5 pasos)  │
│ TRABAJO          │ 🔍 Buscar…                  │ ┃ Qué pasa y cómo seguir  │
│  Inicio          │ ● Título      Estado  hace… │ ┃ [Reintentar] [Abrir]    │
│  Documentos  (2) │   archivo.md                │ Línea de tiempo           │
│  Revisión    (1) │                             │ ● 21:15 Documento…        │
│ CONOCIMIENTO     │                             │                           │
│  Biblioteca …    │                             │ ▸ Detalles técnicos       │
│ SISTEMA  …       │                             │                           │
│ ● Broker         ├─────────────────────────────┴───────────────────────────┤
└──────────────────┴ Barra de estado                   Pausar actualización  ┘
```

Navegación lateral agrupada por intención (Trabajo, Conocimiento, Sistema), con
contadores de lo pendiente y atajos Ctrl+1…Ctrl+0. Diseño en [`DESIGN.md`](DESIGN.md).

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
- Con `single`, una tarea equivale a una inferencia. Con `mixture_of_agents`, `agent` o `auto`, la tarea sigue siendo una unidad opaca para el Orchestrator pero puede contener invocaciones internas acotadas o pasos de razonamiento con herramientas del Broker
- `content.metadata` contiene únicamente correlación allowlist; el Broker no la interpreta
- Solo se usan fuentes introducidas por el usuario (videos capturados, documentos depositados, notas existentes). Sin RSS, vigilancia de documentación ni búsqueda web autónoma
- Toda propuesta de actualización semántica debe citar evidencia local con `source_id` y span. El conocimiento interno del LLM no es evidencia
- `manual_lock: true` en un claim impide su sustitución automática
- Comunicación HTTP con Broker; `KO_BROKER_ADMIN_TOKEN` añade `X-Admin-Token` cuando el despliegue lo exige. Sin token, la cabecera se omite.
- Base SQLite por usuario en `%LOCALAPPDATA%/Knowledge Orchestrator/data/state/orchestrator.db` con modo WAL
- Integridad mediante estados durables y operaciones idempotentes; no existe transacción única SQLite+NTFS

## Desarrollo

El estado funcional vigente se resume en [`docs/CURRENT_STATE.md`](docs/CURRENT_STATE.md).
La fase 1 implementó la frontera de ingesta y persistencia. Incluye:

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

La UI documental está implementada con Resumen, Documentos, Biblioteca, Revisión, Organización y Ajustes. El mantenimiento semántico durable está implementado en la fase 6.

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

Para probar sin escribir en la carpeta de datos habitual:

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

La fase 3 implementa el cliente HTTP asíncrono y la validación inmediata del contrato Broker v2.8, con identificadores locales separados de los `task_id` asignados por el Broker. Incluye workflows durables simples o por chunks, síntesis con dependencias, creación `202`, replay idempotente `200`, detección de conflictos `409`, dispatcher y poller independientes, esperas no terminales `waiting_for_memory` y `waiting_for_dependencies`, cancelación idempotente, reintentos transitorios, recuperación tras reinicio y descubrimiento periódico de modelos. La negociación de capacidades admite dependencias, skills con salida de red, mapas de presets, planificación y formatos de ingesta sin rechazar futuras ampliaciones. Los avisos del resultado y las citas sin respaldo se conservan y aparecen en la cronología. Los documentos enviados inline conservan el chunking local; el `map_reduce` del Broker queda reservado para futuros flujos que adjunten un `broker_file` ya ingerido.

El dispatcher envía todos los chunks disponibles sin esperar resultados. En el baseline `single`, el Broker procesa una inferencia a la vez. La futura opción Multitasking_LLM mantendrá un solo workflow Broker activo, aunque podrá ejecutar invocaciones internas mediante planificación adaptativa. El worker de red está separado del watcher y del hilo principal.

Véase [`docs/Phase_3_Broker.md`](docs/Phase_3_Broker.md). Además de los dobles de prueba, se verificó el proceso FastAPI real del AI Broker desde alta y replay idempotente hasta publicación final.

### Fase 4 — Publicación y revisión

La fase 4 publica el resultado final en Obsidian mediante intención SQLite, temporal sincronizado, instalación que nunca sustituye un destino existente (enlace duro o, en volúmenes sin enlaces duros como Google Drive, renombrado no destructivo de Windows) y verificación SHA-256. Con «Exigir revisión humana antes de publicar» el resultado queda como borrador hasta aprobarlo en Documentos. La captura solo pasa a `COMPLETED` después de guardar la nota y archivar la fuente. El arranque recupera publicaciones incompletas.

El rechazo retira nota y fuente a `rejected` sin destruirlas. El reprocesado copia la evidencia conservada a `processing` y crea una revisión nueva con identificadores idempotentes distintos. Véase [`docs/Phase_4_Publication.md`](docs/Phase_4_Publication.md).

### Fase 5 — Multitasking_LLM

La integración con `mixture_of_agents/fast` y con `auto` (meta-router del Broker, contrato v2.8) está implementada mediante una política versionada por perfil y paso. `single` sigue siendo el valor predeterminado; los chunks permanecen en `single` y las estrategias pesadas se reservan para síntesis o pasos `single` habilitados expresamente.

La integración incluye validación de metadata de consenso, progreso durable y fallback `single` restringido a fallos de quorum/capacidad. AI Broker ya dispone de providers reales y catálogo; la activación por defecto sigue esperando el benchmark representativo. Véanse [`docs/Phase_5_Multitasking.md`](docs/Phase_5_Multitasking.md) y [`docs/Study_Multitasking_LLM.md`](docs/Study_Multitasking_LLM.md).

### Fase 6 — Mantenimiento semántico

Cada nota publicada crea un job durable de extracción de claims. El modelo elige frases numeradas de la nota y tramos numerados de la captura original (no copia texto); la aplicación comprueba el respaldo en la fuente y marca cada afirmación como `SOURCE`, `MODEL_LINKED` o `SUMMARY_ONLY`. Solo las respaldadas por la fuente originan candidatos, que se recuperan por tema, entidades, FTS5 y embeddings opcionales.

Las comparaciones generan relación, confianza, impacto, patch y diff. Ningún cambio se aplica automáticamente: `manual_lock` bloquea la propuesta y los demás candidatos quedan `PENDING_REVIEW` hasta aprobación humana. La aprobación conserva la revisión anterior y usa escritura sincronizada más reemplazo atómico recuperable.

Véase [`docs/Phase_6_Semantic_Maintenance.md`](docs/Phase_6_Semantic_Maintenance.md).

### Fase 7 — Centro de trabajo y revisión

La interfaz se abre con:

```powershell
$env:PYTHONPATH='src'
python -m knowledge_orchestrator.app --ui
```

Incluye Resumen, Documentos, Biblioteca, Revisión, Organización y Ajustes. Documentos es una vista maestro-detalle con filtros, búsqueda, cronología y acciones contextuales. Biblioteca consulta las notas publicadas y permite localizar cada resultado en Obsidian. La interfaz permite importar Markdown, marcar varios documentos y enviarlos en lote, reintentar tareas fallidas con una clave idempotente nueva, cancelar trabajos activos y cerrar incidencias sin borrar su historial. Refresca cada 2 segundos desde snapshots SQLite de solo lectura, conserva toda la selección válida y nunca cambia automáticamente el objetivo de una acción. La conexión y el token del Broker se aplican al guardarlos, sin reiniciar la aplicación.

La pestaña Revisión presenta candidatos semánticos `PENDING_REVIEW` en lenguaje humano, confirma cada decisión y usa los servicios atómicos existentes. La API documental local está disponible; sus consumidores se crean y revocan desde «Automatización y API». Véase [`docs/Phase_7_UI.md`](docs/Phase_7_UI.md).

### Fase 8 — Operación y empaquetado

Operación básica:

```powershell
$env:PYTHONPATH='src'
python -m knowledge_orchestrator.app --backup
python -m knowledge_orchestrator.app --full-backup
python -m knowledge_orchestrator.app --restore C:\ruta\copia.zip --root C:\carpeta\vacia
python -m knowledge_orchestrator.app --diagnostics C:\tmp\ko-diagnostics.zip
```

`--full-backup` guarda en un ZIP la base, las fuentes archivadas y un manifiesto con hashes (las notas de la bóveda se referencian, no se copian); `--restore` lo restaura en una carpeta vacía verificando cada hash. Las credenciales no viajan: hay que volver a configurar el Broker y Obsidian.

El backup usa la API consistente de SQLite y se guarda en `backups/`. El diagnóstico genera un ZIP con contadores, entorno, configuración y líneas completas de logs saneadas. No adjunta SQLite ni archivos de notas. Oculta campos de credenciales reconocidos y el token Broker configurado, también dentro de JSON textual. Los mensajes libres antiguos pueden contener otros datos privados: el saneamiento no garantiza anonimización de cualquier texto. Los archivos originales no se reescriben al exportar.

Build Windows:

```powershell
.\scripts\build_windows.ps1 -Clean
```

El script crea una aplicación gráfica portable en `dist\Knowledge-Orchestrator`. Si Inno Setup 6 está instalado, también genera `dist\installer\Knowledge-Orchestrator-Setup.exe`, con accesos directos y desinstalador por usuario. El ejecutable empaquetado abre la interfaz directamente.

Véase [`docs/Phase_8_Operations.md`](docs/Phase_8_Operations.md).

Fuentes vigiladas Web/RSS/Atom y su API: [`docs/Source_Monitoring.md`](docs/Source_Monitoring.md).

## AI OS Core como director (0.4.3)

Opcional: sin `KO_CORE_URL` todo funciona como antes. Con `KO_CORE_URL` y el token por app
en `KO_CORE_TOKEN`, `BrokerClient.create_task` (el único camino al Broker: despachador,
mantenimiento semántico y consultas de conocimiento) evalúa antes en AI OS Core la política
`knowledge_orchestrator:broker` con el propósito de la petición (`study_notes`,
`semantic_maintenance`…) y su `data_classification`, y solo envía con un ALLOW ejecutable:

- denegada: la tarea falla con código `CORE_DENIED` y el motivo de Core, sin tocar el Broker;
- Core no contesta: no se envía y se reintenta con el backoff de siempre;
- cada tarea deja recibos en Core con su clave de idempotencia (`accepted` al enviarla; el
  estado terminal cuando el sondeo la ve terminar).

Recorrido real: `scripts/verify_ai_os_core.py <core> <token_ko> <token_director> <broker> <carpeta>`
con `KO_BROKER_ADMIN_TOKEN` (7 comprobaciones, verde el 18-oct-2026; runtime real en una carpeta
de usar y tirar).

**0.4.4 — monitor de Core.** Cada tarea se ve en vivo en `<core>/monitor`: la autorización y los
recibos llevan como `flow_id` la clave de idempotencia de la tarea, y el envío y el estado final
se cuentan como salto KO → Broker (petición y luego respuesta o error, con su duración). Si el
monitor no contesta, la tarea no se entera.

**0.4.5 — la ventana sobrevive a un fallo de lectura.** Uso real 19-oct: con la base en Google
Drive, una lectura falló con `sqlite3.OperationalError: disk I/O error` justo al terminar el
arranque. Como el siguiente refresco se programaba al final de `_refresh`, esa excepción lo
cancelaba para siempre: «Documentos» se quedaba vacío y el reloj, parado. Ahora cada paso del
refresco va protegido, el fallo queda en el registro con su traza, la barra de estado lo dice y
se reintenta a los 2 s. La causa de fondo sigue siendo la base SQLite en una carpeta sincronizada.

**Copia periódica a otra carpeta.** Si `paths.json` (en `%LOCALAPPDATA%\Knowledge Orchestrator\config`)
tiene `backup_dir`, el trabajador `periodic-backup` comprueba cada minuto si la última copia tiene más de
6 horas. Si es así, deja allí una copia integral restaurable (`knowledge-orchestrator-full-<fecha>.zip`,
la misma de `--full-backup`) y conserva las 10 más recientes. Sirve para tener la base en disco local
y la copia en Google Drive: un ZIP escrito de una vez no sufre el `disk I/O error` de SQLite. Con
`--root` o `KO_ROOT` no se activa. Guardar las carpetas desde Ajustes conserva `backup_dir`. Se
restaura con `--restore <zip> --root <carpeta vacía>`.

**Inicio automático de la API.** Al terminar el arranque de la ventana, si la casilla «Iniciar al
abrir la aplicación» (Automatización y API) está marcada, que es lo predeterminado, y hay al menos un
consumidor, la API se inicia sola en el último puerto con el que se inició a mano (si no hay ninguno,
8766, u 8767 si el puente de Obsidian usa el 8766). La preferencia vive en `state/api_settings.json`, junto a
los datos: una raíz de pruebas no hereda la real. Un puerto ocupado se muestra en esa pantalla
igual que al pulsar el botón. No se pasa por AI OS Core: Core solo autoriza envíos al Broker y no
tiene canal para arrancar procesos.

## Licencia

MIT
