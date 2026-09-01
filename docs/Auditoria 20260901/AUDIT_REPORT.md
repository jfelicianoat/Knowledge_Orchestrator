# Resumen ejecutivo

- **Modo de análisis:** proyecto ZIP, revisión estática por lectura. No se ha asumido ejecución ni se han usado resultados de tests como evidencia de comportamiento.
- El diseño general es sólido para un MVP local: capas `domain/repositories/services/integrations/worker/ui`, SQLite WAL, intenciones durables, operaciones idempotentes y fronteras explícitas con AI Broker.
- **High / Obsolescence:** `pyproject.toml` admite Python `>=3.10`; Python 3.10 está en fase de seguridad y tiene EOL programado para **octubre de 2026**. A fecha 2026-09-01 queda aproximadamente un mes de soporte.
- **High / Dependency & Reliability:** no hay lockfile ni constraints reproducibles. Los rangos son amplios (`watchdog>=4,<7`, `httpx>=0.27,<1`, etc.), por lo que dos instalaciones en fechas distintas pueden resolver dependencias diferentes.
- **Medium / Correctness:** `src/knowledge_orchestrator/worker/broker_worker.py` compara `contract_version != "2.8"` y emite warning, mientras `docs/CURRENT_STATE.md` declara compatibilidad con 2.9. Es deuda reconocida por el propio repositorio y puede producir diagnóstico falso.
- **Medium / Security/Config:** el Broker usa por defecto `http://broker-machine.local:8765`; el token es opcional. Esto es coherente con el MVP LAN documentado, pero debe considerarse una frontera de confianza: fuera de una LAN controlada falta confidencialidad del transporte.
- **Medium / Maintainability:** `ui/dashboard.py` tiene ~1.189 líneas y concentra construcción, renderizado, acciones y estado de varias pantallas. Es el mayor punto de acoplamiento de UI.
- **Medium / Maintainability:** varias funciones superan ~100 líneas (`workflow_repository.apply_status`, validadores de contrato, `ingestion.ingest`, `runtime.build_runtime`). No es un bug por sí solo, pero aumenta coste de cambio y testeo.
- **Medium / Delivery:** no se encontraron workflows de CI en `.github/workflows` ni equivalente. El repositorio documenta comandos de verificación, pero no hay quality gate automatizado visible.
- **Low / Documentation:** README/System Architecture mencionan `matplotlib`, pero no aparece importado ni declarado como dependencia en `pyproject.toml`; conviene corregir deriva documental.
- No se afirma que existan CVEs concretos en producción: sin lockfile no se conoce la versión exacta instalada de cada dependencia. La evaluación de vulnerabilidades debe hacerse sobre un lock/SBOM real.

# Mapa del sistema

## Árbol resumido

```text
Knowledge_Orchestrator-master/
├── pyproject.toml
├── README.md / System_Architecture.md / Data_Contracts.md / PRODUCT.md
├── docs/
├── scripts/
├── src/knowledge_orchestrator/
│   ├── app.py / runtime.py / config.py
│   ├── domain/
│   ├── repositories/
│   ├── services/
│   ├── integrations/
│   ├── worker/
│   ├── ui/
│   └── migrations/ (001..010)
└── tests/
```

## Clasificación

- **Código:** 51 módulos Python bajo `src/`.
- **Persistencia:** SQLite + 10 migraciones SQL.
- **Integraciones:** cliente HTTP asíncrono `httpx` hacia AI Broker.
- **UI:** Tkinter/ttk.
- **Filesystem:** watchdog + movimientos/reemplazos atómicos.
- **Tests:** suite Python bajo `tests/`.
- **Config/build:** `pyproject.toml`, scripts Windows e instalador Inno Setup.
- **CI:** no detectado en el snapshot revisado.

## Entrypoints

- `pyproject.toml` → `knowledge-orchestrator = knowledge_orchestrator.app:main`.
- `src/knowledge_orchestrator/app.py` → crea runtime/UI.
- `src/knowledge_orchestrator/runtime.py::build_runtime()` → composition root.
- `OrchestratorRuntime.start()` → recuperación, watcher y worker Broker.
- `start_orchestrator.bat` y `scripts/build_windows.ps1` → operación/build Windows.

# Cómo funciona

1. Se resuelven rutas locales y configuración del Broker.
2. `build_runtime()` inicializa SQLite, aplica migraciones y construye repositorios/servicios.
3. `recover_once()` reconcilia estado durable, publicaciones, semántica y workflows antes de aceptar trabajo nuevo.
4. `InboxWatcher` detecta entradas; la ingesta valida estabilidad/contrato y mueve de inbox → staging → processing con hash y estado SQLite.
5. Clasificación/perfiles generan workflows y prompts.
6. `BrokerWorker` despacha/pollea AI Broker mediante `BrokerClient`.
7. `PublicationService` publica a Obsidian con intención durable + temporal + `os.replace`, y archiva fuente.
8. Mantenimiento semántico extrae/compara claims y mantiene propuestas revisables.
9. UI consume snapshots/eventos y emite comandos; la intención arquitectónica es que no acceda directamente a HTTP/SQLite/filesystem.

# Hallazgos por fichero

## `pyproject.toml`
### Rol del fichero
Manifiesto de build, runtime, dependencias y tooling.

### Hallazgos

| Severidad | Tipo | Impacto | Prob. | Riesgo | Evidencia | Recomendación | Cambio sugerido |
|---|---|---:|---:|---:|---|---|---|
| High | Obsolescence | 4 | 5 | 20 | `requires-python = ">=3.10"`; Python 3.10 EOL 2026-10 | Elevar mínimo | Conservador: `>=3.11`; modernización: `>=3.13` |
| High | Dependency | 4 | 4 | 16 | No existe lockfile/constraints | Resolver y versionar lock reproducible | `uv.lock`, `requirements.lock` o constraints con hashes |
| Medium | Testing | 3 | 4 | 12 | `pytest>=8,<9`, `mypy>=1.10,<2` bloquean majors actuales | Actualizar en rama dedicada | Modernización: pytest 9 / mypy 2 |
| Medium | Tooling | 3 | 3 | 9 | `setuptools>=68` sin tope/lock | Fijar build env reproducible | Pin/lock de backend de build |

## `src/knowledge_orchestrator/worker/broker_worker.py`
### Rol del fichero
Bucle asíncrono del Broker: dispatch, polling, capabilities, health, cancelación y eventos.

### Hallazgos

| Severidad | Tipo | Impacto | Prob. | Riesgo | Evidencia | Recomendación | Cambio sugerido |
|---|---|---:|---:|---:|---|---|---|
| Medium | Correctness | 3 | 5 | 15 | líneas ~158-163: espera literal `"2.8"` | Alinear con contrato aceptado | aceptar 2.8/2.9 o comparar major/minor compatible |
| Medium | Maintainability | 3 | 3 | 9 | `_run_async` agrupa múltiples responsabilidades | Extraer ciclos coordinados | scheduler pequeño + servicios de health/capabilities |

## `docs/CURRENT_STATE.md`
### Rol del fichero
Fuente documental vigente según el propio repositorio.

### Hallazgos
- Declara explícitamente la deuda del warning 2.8 frente a 2.9. Esto confirma que el hallazgo anterior **no es inferido**.
- Declara pendiente una prueba integral real Plugin → Orchestrator → Broker → Obsidian; por tanto, la release no debería tratar la suite local como evidencia E2E.

## `src/knowledge_orchestrator/config.py`
### Rol del fichero
Rutas locales y settings del Broker.

### Hallazgos

| Severidad | Tipo | Impacto | Prob. | Riesgo | Evidencia | Recomendación | Cambio sugerido |
|---|---|---:|---:|---:|---|---|---|
| Medium | Security/Config | 4 | 3 | 12 | URL default `http://broker-machine.local:8765`; token opcional | Documentar trust boundary y ofrecer HTTPS/token obligatorio para despliegues no-LAN | perfil `lan` y perfil `hardened`; fail-fast si URL no segura fuera de LAN |
| Low | Config | 2 | 3 | 6 | defaults Windows/locales dentro de código | Externalizar overrides de paths de forma uniforme | config tipada + validación al arranque |

## `src/knowledge_orchestrator/integrations/broker_client.py`
### Rol del fichero
Cliente HTTP asíncrono y traducción de errores de AI Broker.

### Hallazgos
- Positivo: timeout configurable y clasificación transient/permanent.
- Riesgo medio: `401/403` se tratan como transitorios por diseño. Es válido para rotación de token, pero una credencial mal configurada permanentemente puede prolongar reintentos. Añadir telemetría/contador y un estado operacional explícito `AUTH_REQUIRED`.

## `src/knowledge_orchestrator/repositories/database.py`
### Rol del fichero
Conexión SQLite, transacciones, WAL y migraciones.

### Hallazgos
- Positivo: `foreign_keys`, `busy_timeout`, WAL y `BEGIN IMMEDIATE` donde corresponde.
- Low / Correctness: `connect(readonly=True)` abre la base con `sqlite3.connect(self.path)` y luego aplica `PRAGMA query_only`. No es un open OS-level read-only; si el fichero no existe, puede crearse. Para snapshots/diagnóstico, usar URI `mode=ro` cuando la intención sea estrictamente solo lectura.

## `src/knowledge_orchestrator/services/publication.py`
### Rol del fichero
Publicación, rechazo y reproceso durable de notas.

### Hallazgos
- Positivo: valida tamaño/nulos/frontmatter, sanea nombres, usa hash, temporal, `fsync` y `os.replace`.
- Medium / Reliability: `os.replace` es atómico solo dentro del mismo filesystem/volumen; el propio diseño lo reconoce para staging/processing. Debe validarse también para las rutas de vault/rejected/completed configurables y fallar con diagnóstico claro si cruzan volúmenes en operaciones que dependen de replace.

## `src/knowledge_orchestrator/services/ingestion.py`
### Rol del fichero
Pipeline de ingestión y transición durable de archivos.

### Hallazgos
- Medium / Maintainability: `ingest()` ronda 119 líneas y mezcla validación, deduplicación, staging, persistencia y compensación. Extraer pasos explícitos reducirá el riesgo de regresión de recuperación.
- Positivo: diseño orientado a recuperación y preservación de evidencia.

## `src/knowledge_orchestrator/repositories/workflow_repository.py`
### Rol del fichero
Persistencia y transición de workflows/tareas Broker.

### Hallazgos
- Medium / Maintainability: `apply_status()` ronda 159 líneas; es uno de los hotspots de lógica de estado. Recomiendo separar parseo de respuesta, validación de transición y persistencia, conservando una sola transacción.

## `src/knowledge_orchestrator/domain/broker_contracts.py`
### Rol del fichero
Validación del contrato de entrada/salida del Broker.

### Hallazgos
- Medium / Maintainability: dos validadores superan ~120 líneas. Extraer validadores por sección/campo y tests parametrizados.
- Positivo: validación explícita y normalización son preferibles a consumir payloads sin contrato.

## `src/knowledge_orchestrator/domain/contracts.py`
### Rol del fichero
Contrato Markdown de entrada.

### Hallazgos
- Positivo / Security: usa `yaml.load(..., Loader=_UniqueKeySafeLoader)` con loader derivado de safe loader; el uso de `yaml.load` no debe clasificarse automáticamente como unsafe. La suite además contiene un fixture con `!!python/object/apply` para probar rechazo.
- Mantener una prueba de regresión que garantice que el loader nunca derive de `FullLoader`/`UnsafeLoader`.

## `src/knowledge_orchestrator/ui/dashboard.py`
### Rol del fichero
Ventana principal y pantallas UI.

### Hallazgos

| Severidad | Tipo | Impacto | Prob. | Riesgo | Evidencia | Recomendación | Cambio sugerido |
|---|---|---:|---:|---:|---|---|---|
| Medium | Architecture | 4 | 4 | 16 | ~1.189 líneas, 53 funciones/métodos | Dividir por vista/controlador | `HomeView`, `WorkView`, `ReviewView`, `TopicsView`, `ConfigView` |
| Medium | Testing | 3 | 3 | 9 | alto volumen de render/actions en una clase | Encapsular estado/presenters testeables | view-models/snapshot mappers sin Tk |

## `src/knowledge_orchestrator/services/operations.py`
### Rol del fichero
Logging, backup y diagnóstico.

### Hallazgos
- Positivo: logging JSON, rotación y sanitización de claves sensibles.
- Medium / Security: sanitización regex es defensa best-effort; no debe sustituir la regla de no loggear secretos. Añadir tests para headers JSON, bearer tokens, URLs con query secrets y objetos anidados.

## `README.md` / `System_Architecture.md`
### Rol del fichero
Uso y arquitectura.

### Hallazgos
- Low / Documentation: ambos mencionan `matplotlib`, pero no aparece en imports ni en `pyproject.toml`. Eliminarlo del stack o restaurar la dependencia/uso si realmente es requisito.
- Mantener `docs/CURRENT_STATE.md` como fuente vigente y reducir duplicación normativa.

# Hallazgos transversales

## Arquitectura
- La separación por capas es razonable y el `runtime.py` actúa como composition root.
- El mayor acoplamiento se concentra en UI y en repositorios con máquinas de estado grandes.
- No se observó un contenedor DI complejo: esto es positivo para el tamaño actual.

## Fiabilidad/resiliencia
- Fortalezas: WAL, intents, idempotencia, recuperación, hashing, `fsync`, temporales.
- Riesgos: operaciones de archivos cruzando volúmenes; ausencia de E2E archivado; backoff/auth operacional poco explícito.

## Rendimiento
- No se identificó por lectura un hotspot crítico demostrable.
- FTS5/SQLite y bucles de polling son adecuados para un desktop MVP; cualquier afirmación de rendimiento requiere medición.

## Seguridad
- Frontera principal: HTTP LAN + token opcional.
- Buenas señales: YAML seguro, límites de tamaño, saneado de filenames, diagnóstico sanitizado.
- Falta evidencia de SCA/secret scanning automatizado en CI.

## Observabilidad
- Existe logging JSON y eventos UI.
- Falta, en el snapshot, un quality gate operativo con métricas/trazas. Para desktop local, métricas simples de colas, retries, latencia Broker, publicaciones y recuperaciones serían suficientes.

## Tests
- Hay una suite amplia y organizada por fases.
- No se ejecutó en esta auditoría.
- Falta E2E real archivado, reconocido por `docs/CURRENT_STATE.md`.

## Configuración
- Settings concentrados y tipados con dataclasses.
- Conviene separar perfil LAN/hardened y validar rutas/volúmenes al arranque.

## Dependencias
- Producción: PyYAML, watchdog, httpx.
- Dev: pytest, ruff, mypy.
- Problema principal: **resolución no reproducible** y mínimo Python casi EOL, no una dependencia productiva claramente abandonada.

# Estándares recomendados

- Python target explícito y matriz de CI.
- Lockfile reproducible + hashes/SBOM.
- Ruff + mypy + tests como checks de PR.
- Conventional logging fields: `event`, `workflow_id`, `capture_id`, `task_id`, `attempt`, `latency_ms`.
- ADR para frontera de confianza Broker LAN vs hardened.
- Views UI separadas de presenters/view-models.
- Regla: una transición durable compleja = función de dominio pequeña + repositorio transaccional.
- Runbook de recuperación y backup/restore.
- PR template con cambios de contrato/migración/recovery.

# Roadmap

## Quick wins
1. Corregir warning Broker 2.8/2.9.
2. Añadir CI con Python 3.11/3.13 y comandos ya documentados.
3. Introducir lockfile.
4. Cambiar mínimo Python conservador a 3.11.
5. Corregir documentación `matplotlib`.
6. Test de `Database.connect(readonly=True)` y URI `mode=ro`.

## Medio plazo
1. Extraer vistas desde `dashboard.py`.
2. Partir `apply_status`, `ingest` y validadores largos.
3. Perfil de seguridad hardened para Broker.
4. Métricas operativas y tests de sanitización.
5. Automatizar backup/restore test.

## Largo plazo
1. Python 3.13 como baseline moderno.
2. Contract tests E2E con AI Broker 2.8/2.9.
3. Release evidence Plugin → Orchestrator → Broker → Obsidian.
4. SBOM + SCA/secret scanning.
5. Refactor progresivo de state machines hacia servicios de transición explícitos.

# Tareas para ejecución

| ID | Título | Archivos | Prioridad | Severidad/Riesgo | Esfuerzo |
|---|---|---|---|---|---|
| AUD-001 | Alinear contrato Broker 2.9 | `worker/broker_worker.py`, tests | P0 | Medium/15 | S |
| AUD-002 | Subir mínimo Python | `pyproject.toml`, scripts, docs | P0 | High/20 | S |
| AUD-003 | Añadir lock reproducible | manifest + lock nuevo | P0 | High/16 | S |
| AUD-004 | Crear CI | `.github/workflows/*` | P0 | Medium/12 | S |
| AUD-005 | Endurecer perfil Broker | `config.py`, `broker_client.py`, docs | P1 | Medium/12 | M |
| AUD-006 | Separar dashboard | `ui/dashboard.py` + módulos nuevos | P1 | Medium/16 | L |
| AUD-007 | Reducir state-method hotspots | repositories/services/domain | P1 | Medium/12 | M |
| AUD-008 | Validar atomicidad de rutas | config/publication/ingestion | P1 | Medium/12 | M |
| AUD-009 | SCA/SBOM/secret scan | CI/config | P1 | Medium/12 | M |
| AUD-010 | Evidencia E2E de release | tests/scripts/docs | P1 | Medium/12 | M |

# Supuestos y límites del análisis

- Fuente primaria: ZIP `Knowledge_Orchestrator-master.zip` suministrado en la conversación.
- El repositorio público se consultó solo como contexto; los hallazgos de código se basan en el ZIP.
- Revisión estática: **no se ejecutaron** tests, app, build, instalador ni Broker.
- No se conocen versiones efectivamente instaladas porque no hay lockfile.
- No se afirma ausencia de CVEs. Una auditoría CVE precisa requiere lock/SBOM.
- Fecha de referencias online: **2026-09-01**.
