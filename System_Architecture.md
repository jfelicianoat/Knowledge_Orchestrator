# System Architecture: YouTube Knowledge Pipeline

> **Precedencia:** la sección `Arquitectura Normativa del MVP` resuelve cualquier contradicción con ejemplos anteriores.



## Visión Global del Ecosistema



Sistema distribuido de 3 aplicaciones independientes que transforman contenido de YouTube en conocimiento estructurado mediante LLMs locales y externos, optimizando costes y maximizando la calidad de extracción.



## Componentes del Sistema



### 1. YT Capture Agent (Chrome Extension)

**Responsabilidad:** Captura resiliente de metadata y transcripciones de YouTube

**Tecnología:** Chrome Extension Manifest V3

**Output:** Archivos .md estructurados en carpeta de descargas



### 2. Knowledge Orchestrator (Desktop App)  

**Responsabilidad:** Procesamiento inteligente, gestión de colas, aplicación de perfiles

**Tecnología:** Python + CustomTkinter + File Watcher

**Características:** UI con cola visual animada, gestión de temas, sistema de revisión



### 3. AI Broker (Neural Gateway)

**Responsabilidad:** Enrutamiento óptimo a LLMs, gestión de VRAM, control de presupuesto

**Tecnología:** FastAPI + HTMX + Tailwind CSS  

**Características:** Dashboard web, autodescubrimiento de modelos, cancelación de tareas



## Flujo de Datos Completo



```

[Plugin Chrome] -->(archivos .md) [File Watcher] --> [Orchestrator]

                                                           |

                                                    (HTTP/JSON)

                                                           ↓

[Obsidian Vault] <--(archivos .md) [Post-Processor] <-- [AI Broker] --> [LLMs]

                                                                            ↓

                                                                    [Ollama Local]

                                                                    [DeepSeek API]

                                                                    [Ollama Cloud]

```



## Arquitectura de Directorios



```

C:/YT-Pipeline/

├── staging/        # Copias temporales antes del commit y movimiento atómico

├── state/          # SQLite y estado durable del Orchestrator

├── processing/     # Archivos siendo procesados

├── completed/      # Archivos fuente procesados exitosamente  

├── failed/         # Archivos con errores + logs detallados

├── rejected/       # Archivos rechazados desde UI

└── logs/          # Logs del sistema



C:/ObsidianVault/Knowledge/

├── _inbox/         # Notas sin tema asignado

├── IA-y-LLMs/     # Auto-creación de carpetas por tema

├── Desarrollo/

│   ├── Python/

│   ├── Web/

│   └── DevOps/

└── Trading/

    ├── Estrategias/

    ├── Analisis-Tecnico/

    └── Noticias-Mercado/

```



## Stack Tecnológico por Componente



**Plugin Chrome:**

- Chrome Extension API (Manifest V3)

- JavaScript vanilla con estrategia de extracción de 3 niveles

- Sistema de descarga automática a carpeta del navegador



**Knowledge Orchestrator:**

- Python 3.10+ con CustomTkinter (UI moderna)

- watchdog (monitorización de archivos)

- httpx (cliente HTTP asíncrono)

- matplotlib (gráficos integrados)



**AI Broker:**

- FastAPI (backend REST + dashboard web)

- HTMX (actualización en tiempo real sin JavaScript complejo)

- Tailwind CSS (diseño moderno sin CSS custom)

- httpx (comunicación con Ollama y APIs externas)



## Comunicación Entre Componentes



**Plugin → Orchestrator:** `Downloads/YT-Knowledge-Inbox` (sistema de archivos asíncrono)

**Orchestrator → Broker:** HTTP REST con reintentos y fallback

**Broker → LLMs:** HTTP directo (Ollama) + APIs externas



## Decisiones Arquitectónicas Clave



**Separación de Responsabilidades:** Cada app tiene una función única y bien definida

**Resilencia:** Fallos en un componente no afectan a los otros

**Escalabilidad:** Cada servicio puede escalar independientemente

**Reutilización:** El Broker IA sirve para futuros proyectos más allá de YouTube

**Control de Costes:** Enrutamiento inteligente minimiza uso de APIs de pago

## Arquitectura Normativa del MVP

Esta sección consolida las decisiones del hilo original y prevalece sobre ejemplos incompatibles.

### Límites de cada aplicación

- **YT Capture Agent:** captura metadata y transcripción sin procesarlas y descarga un Markdown v1 en la bandeja de entrada del navegador.
- **Knowledge Orchestrator:** valida entradas de cualquier fuente, decide tema y perfil, construye prompts, envía tareas, escribe el resultado en Obsidian y mantiene historial/revisión.
- **AI Broker:** no conoce YouTube ni Obsidian. Descubre modelos, mantiene una cola durable, ejecuta prompts en Ollama o proveedores configurados y controla ejecución serial, cancelación y coste.

### Flujo de datos definitivo

1. El plugin o una fuente externa escribe un Markdown completo en `%USERPROFILE%/Downloads/YT-Knowledge-Inbox`.
2. El Orchestrator espera a que el fichero sea estable y accesible, valida el contrato v1 y crea una copia sincronizada en `C:/YT-Pipeline/staging`.
3. Registra en SQLite el hash y las rutas con estado `STAGED`; solo después del commit mueve la copia mediante `os.replace` a `processing` y elimina el original de inbox.
4. El Orchestrator crea una tarea idempotente en el Broker y consulta su estado hasta obtener resultado o error terminal.
5. En éxito, escribe inmediatamente la nota en la carpeta temática de Obsidian, o en `_inbox` si no hay tema; después mueve el origen a `completed`.
6. La pantalla de revisión permite rechazar una nota ya publicada. Rechazarla la retira del vault, conserva nota y origen bajo `rejected` y permite reprocesar el original.
7. Si el Broker está desconectado, la tarea permanece pendiente y la UI muestra el incidente sin notificaciones del sistema.

### Persistencia y ejecución

- Cada aplicación mantiene su propia base SQLite; no se comparte base de datos entre máquinas.
- El Orchestrator usa un único proceso: Tk en el hilo principal y un worker con bucle `asyncio` para red, filesystem y reintentos.
- El Broker usa un proceso Uvicorn y un único ejecutor LLM. HTTP, dashboard y polling siguen siendo asíncronos, pero nunca hay más de una tarea realizando llamadas a LLMs.
- Todas las transiciones de estado se persisten antes de ejecutar efectos externos y se reanudan de forma segura tras un reinicio.
- La comunicación Orchestrator-Broker usa hostname/mDNS, HTTP en la red privada y, por decisión explícita del usuario, no usa autenticación en el MVP. No debe exponerse el puerto a Internet.

### Fuentes soportadas

`source_type` es extensible. YouTube añade sus campos específicos, pero cualquier fuente puede entrar si aporta `capture_id`, `source_type`, `title`, `captured_at`, `has_transcript` y una sección `## Transcripción`. Los metadatos ausentes permanecen nulos; nunca se inventan.

### Integridad transaccional entre archivos y SQLite

No existe una transacción única que abarque SQLite y NTFS. La integridad se consigue mediante estados durables y operaciones idempotentes:

1. Esperar tres comprobaciones consecutivas sin cambios y hasta tres intentos de apertura si el sistema mantiene el archivo bloqueado.
2. Validar el fichero de inbox contra el contrato v1 antes de copiarlo.
3. Copiarlo a `staging/<capture_id>.md.part`, ejecutar `flush` y `fsync`, calcular SHA-256 y volver a validar la copia.
4. Ejecutar `BEGIN IMMEDIATE`, insertar la captura en estado `STAGED` con hash y rutas, y confirmar la transacción.
5. Tras el commit, usar `os.replace` desde staging a `processing`; ambas carpetas deben estar en el mismo volumen.
6. Actualizar SQLite a `PENDING` y eliminar el original de inbox. Si la eliminación falla, `capture_id` impide un procesamiento duplicado.
7. Al arrancar, reconciliar registros `STAGED` con staging/processing y completar o revertir la operación sin perder el fichero.

Un error de contrato se rechaza antes de staging y se conserva bajo `failed/contracts` con un sidecar de error legible.

### Espera asíncrona y ejecución serial

- El Orchestrator continúa enviando nuevas tareas aunque una anterior permanezca mucho tiempo esperando la respuesta del LLM.
- `POST /api/v1/tasks` solo acepta y persiste la tarea; no espera a que termine el modelo.
- El Broker puede mantener cualquier número de tareas `queued` hasta el límite de cola, pero solo una tarea puede estar `processing`.
- Mientras una tarea está `routing`, `chunking`, `generating` o `synthesizing`, ninguna otra tarea puede iniciar una llamada a ningún LLM, sea Ollama o un proveedor externo.
- Las tareas posteriores permanecen en `queued` y conservan su orden. Solo avanzan cuando la activa termina con éxito, error, cancelación o timeout.
- “Continuar lanzando tareas” significa continuar entregándolas y aceptándolas en la cola del Broker; no significa ejecutarlas en paralelo.
