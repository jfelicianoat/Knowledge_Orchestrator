# Estado vigente de Knowledge Orchestrator

Revisión del núcleo, API, fuentes y mantenimiento: **5 de septiembre de 2026**.
Las capacidades anteriores conservan su revisión del 23 de agosto; consultar las
limitaciones de evidencia real y los registros `Phase_9_Knowledge_Core.md` y `Phase_10_Knowledge_API.md`.

Este documento prevalece para cuestiones de estado y compatibilidad. `README.md` explica
el uso; `System_Architecture.md` y `Data_Contracts.md` contienen el diseño; los documentos
`Phase_*` son registros históricos de cada entrega.

## Responsabilidad

Knowledge Orchestrator convierte capturas y documentos locales en conocimiento publicado
y revisable. Posee la validación de entrada, clasificación, perfiles, prompts, chunking,
workflow, claims, comparación semántica, revisión humana y proyección a Obsidian. AI Broker
solo ejecuta las tareas técnicas que recibe; no conoce el vault ni la semántica del
workflow.

## Flujo durable

```text
inbox -> estabilidad -> validación v1 -> staging + SHA-256 + SQLite
      -> processing -> clasificación -> workflow -> tareas AI Broker
      -> validación de resultados -> publicación atómica -> completed
                                      └-> claims y candidatos de revisión
```

No existe una transacción distribuida entre NTFS, SQLite, Broker y Obsidian. La consistencia
se obtiene con intenciones durables, claves idempotentes, temporales sincronizados,
reemplazos atómicos y reconciliación al arrancar.

## Capas actuales

- `domain`: contratos, estados y errores tipados.
- `repositories`: SQLite, migraciones y transiciones.
- `services`: ingesta, planificación, publicación, semántica y operaciones.
- `integrations`: cliente HTTP de AI Broker.
- `worker`: watcher, dispatcher, poller y trabajo fuera del hilo UI.
- `ui`: Tkinter/ttk, snapshots de solo lectura y puente de eventos al hilo principal.

## Compatibilidad Broker

El validador de dominio acepta las extensiones aditivas del contrato **2.10** y conserva
compatibilidad con respuestas 2.8 y 2.9.

**Deuda saldada (5-sep-2026).** El diagnóstico de `worker/broker_worker.py` comparaba la
capacidad anunciada con la cadena `"2.8"` y avisaba ante cualquier otra versión. Además de
convertir cada Broker nuevo en un aviso permanente —que el operador aprende a ignorar, y
entonces deja de servir para lo que existe—, la comparación por cadenas dice que `"2.10"`
es anterior a `"2.9"`. Ahora se compara contra `MINIMUM_CONTRACT_VERSION` por número
(`contract_at_least`), y solo avisa un Broker **por debajo** del mínimo. Cubierto por
`test_a_newer_contract_is_retained_without_a_warning` y
`test_a_contract_below_the_minimum_is_reported_as_warning`.

Del contrato 2.10 el orquestador usa:

- **`auxiliary_invocations: false`** (§8.4) cuando el perfil declara `confidential` o
  `local_only`. El sondeo en sombra del Broker respeta la clasificación de datos, pero
  «un modelo local» no es «el modelo que yo aprobé», y aquí se trabaja sobre notas del
  vault de su dueño. El cliente **retira** el campo si el Broker no anuncia el opt-out:
  la validación del Broker es `extra="forbid"`, así que pedir una garantía adicional a un
  Broker que no la tiene mataría la tarea entera con un 422.
- **`GET /tasks/{id}/invocations`** (§8.1) con `is_contractual_invocation`, que lee el
  booleano `contractual` y solo cae al nombre del rol contra un Broker anterior al 2.10.
- **`GET /tasks/{id}/artifacts`** (§8.3) con `final_artifact`, que filtra por `final` y no
  por `artifact_type`: la lista de tipos crece con cada estrategia nueva.

La autenticación no se presupone ni se descarta: `KO_BROKER_ADMIN_TOKEN` configura
`X-Admin-Token`. Sin token, el cliente omite la cabecera y solo funcionará si el despliegue
acepta ese acceso. Un 401/403 se trata como credencial rotada y recuperable.

## Capacidades implementadas

- watcher `watchdog` con rescan, estabilidad, cancelación y cuarentena;
- ingesta v1, deduplicación, recuperación y fuentes genéricas controladas;
- temas, perfiles versionados, prompts, chunking y síntesis;
- tareas Broker durables, polling, cancelación, modelos y estrategias configurables;
- publicación Obsidian con intención, hash y revisiones;
- extracción de claims, FTS5, embeddings opcionales, comparación, diff y aprobación;
- entidades y vínculos con claims, seis estados explícitos de vigencia, sucesiones e
  histórico de decisiones inmutable (migración aditiva 012);
- consultas current/historical/all, revisión optimista de estado y reconciliación
  documental al arrancar, sin sobrescribir ediciones humanas;
- API local v1 autenticada, documentos/revisiones, entidades/claims, búsqueda FTS/vectorial,
  consultas IA durables con citas exactas e ingesta controlada (`docs/Knowledge_API.md`);
- fuentes Web/RSS/Atom con configuración versionada, scheduler durable, hashes por ítem,
  backoff, revisión de novedades y entrega idempotente al flujo documental;
- mantenimiento: propuestas versionadas con impacto/riesgos/procedencia, edición y
  decisiones optimistas, contradicciones explícitas, sucesor en la nota destino,
  histórico estructurado o snapshot, reindexado y reconciliación de evidencia derivada;
- validación de ambas notas antes de aplicar/recuperar, protección de claims solapados
  y de dependencias durante publicaciones y revisiones concurrentes;
- UI de Resumen, Documentos, Biblioteca, Conocimiento, Fuentes, Revisión, Organización
  y Ajustes; explorador de claims con filtros de vigencia/entidad/texto, evidencia,
  sucesiones e histórico, con reconciliación documental en segundo plano;
- Operaciones: pipeline navegable, novedades de todas las fuentes, análisis y propuestas,
  filtros de incidencias, histórico de decisiones y lectura de la revisión anterior;
  accesos al documento, fuente y revisión individual, incluidos conflictos;
- backup SQLite, diagnóstico saneado y empaquetado Windows.

## Límites y evidencia pendiente

- Hay Web y RSS/Atom; no hay rastreo recursivo, GitHub releases ni búsqueda web autónoma.
- La evolución por fases 9–14 está en curso: fases 9 y 10 superan sus checkpoints locales;
  fase 11 verifica núcleo/API/recuperación, con pantalla y red pendientes por entorno.
  La fase 12 supera núcleo/API: 231 pruebas, 230 pasan y una omisión Tcl/Tk; ruff/mypy pasan.
  Primer incremento de fase 13: 236 pruebas, 234 pasan y dos omisiones Tcl/Tk; ruff/mypy
  pasan (110 archivos). El explorador está implementado; su render sigue sin verificar.
  Centro de operaciones, gobernanza y verificaciones externas siguen pendientes según
  `Knowledge_Lifecycle_Plan.md`.
- La descarga pública devuelve NETWORK_DENIED. La prueba visual de Fuentes no se ejecuta
  porque Tcl/Tk no inicializa init.tcl en este entorno. Véase `Phase_11_Source_Monitoring.md`.
- La consulta real al Broker desde el entorno de desarrollo está sin verificar: el socket
  saliente devuelve WinError 10013 antes de recibir HTTP. La API local sí pasó prueba HTTP.
- Ningún claim sustituye una nota sin revisión humana; `manual_lock` lo impide siempre.
- Los embeddings son opcionales y no sustituyen la coincidencia exacta de spans.
- La prueba integral real Plugin -> Orchestrator -> Broker -> Obsidian debe ejecutarse y
  archivarse como evidencia de release; las pruebas unitarias y de integración parcial no
  demuestran por sí solas el entorno completo.

## Verificación

```powershell
$env:PYTHONPATH = "src"
python -B -m unittest discover -s tests -v
python -m ruff check src tests
python -m mypy src
```
