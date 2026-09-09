# Estado vigente de Knowledge Orchestrator

Revisión del núcleo, API, fuentes, mantenimiento y gobernanza: **9 de septiembre de 2026**.
Las capacidades anteriores conservan su revisión del 23 de agosto; consultar las
limitaciones de evidencia real y los registros `Phase_9_Knowledge_Core.md` y `Phase_10_Knowledge_API.md`.

Este documento prevalece para cuestiones de estado y compatibilidad. `README.md` explica
el uso; `System_Architecture.md` y `Data_Contracts.md` contienen el diseño; los documentos
`Phase_*` son registros históricos de cada entrega.

**Ensayo local de Obsidian (9-sep-2026):** ya es accesible la copia facilitada por el
usuario. Se prepararon el puente desactivado y cinco notas ficticias, conservando por
hash los 140 archivos anteriores examinados. Ocho de las diez notas visibles existentes
no son UTF-8 válido y la base copiada contiene cero notas registradas. El runtime no se
inició ni se migró esa base. Esta preparación no acredita ejecución en Obsidian ni cierra
los escenarios reales; detalle en `docs/Obsidian_Trial_Checkpoint.md`.

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
- revisión por lotes con planes inmutables, confirmación humana, selección o todas
  las pendientes, resultados parciales, recuperación y API con aislamiento de consumidor;
  comparación antes/después e historial de lotes en UI, con I/O fuera del hilo Tk.
- Servicios: listener API local controlado desde la sesión, consumidores y permisos
  sin credenciales visibles, actividad acotada y estado de vigilancia/análisis/lotes;
  pruebas HTTP reales de loopback para autenticación, permisos, cierre y reinicio.
- gobernanza inicial: políticas con ámbito explícito/versiones, decisiones auditables,
  control global pausado y simulación durable sin publicaciones (migración 017).
  Ejecutor de dominio con cupos diarios y por ejecución, autorización transaccional,
  recuperación y recibos implementado (migración 018). Planificador periódico conectado
  al runtime (migración 019), con arrendamientos, páginas, planes deduplicados y errores
  recuperables. Controles de políticas y auditoría por API con permiso `governance`
  implementados: creación/edición, simulación idempotente, autorización ligada a la
  simulación revisada y pausa versionada (migración 020). UI de políticas integrada en
  Servicios: configuración, simulación por páginas, autorización, pausa independiente
  e historial. Lógica verificada; render pendiente. La revisión independiente del
  puente propuesta/política y sus correcciones no deja hallazgos materiales. Reversión
  conservadora de dominio implementada (migración 021), con planes, reservas, decisión
  explícita, revisiones preservadas y recuperación. API de reversión con permiso review,
  planes propios por consumidor y recibos; UI Revisión → Publicaciones y reversión con
  comparación, motivo y auditoría. Revisión independiente de este incremento sin
  correcciones pendientes; render nativo aún no acreditado.
  Guías: `Automation_Governance.md` y `Maintenance_Reversion.md`.
  Navegación de políticas/fuentes/historial corregida ante lecturas fallidas, borrador
  e identidad conservados y simulaciones siguientes idempotentes tras respuesta perdida.
  Prompts de extracción/comparación con instrucciones de fuente explícitamente
  no autorizantes y delimitadores JSON protegidos; pruebas adversarias de documento,
  contratos, manual_lock, confianza y ausencia de publicación no autorizada.
  Evaluar con política conecta la revisión individual con una simulación de la propuesta
  y revisión exactas; preserva borradores y snapshots históricos. Los assessments nuevos
  distinguen evaluación de política pendiente de elegibilidad real. Un registro histórico
  de otra propuesta/revisión no permite autorizar con el filtro activo.
  Transiciones de análisis y propuestas auditadas en la misma transacción, incluidos
  reintentos/recuperación, intención y conflictos. Publicación enlazada a actor,
  revisión, lote/ejecución y sucesor. Eventos nuevos sin texto de documentos/errores
  remotos y sin duplicados por repetición de estados. Matriz de campos y trazabilidad
  en `Proposal_Audit_Evidence.md`.
  Ver trazabilidad desde Revisión y Propuestas/Histórico de decisiones permite recorrer
  versiones, comparación, evidencia, tareas/modelos reportados y decisión/publicación.
  Distingue las simulaciones de ejecución y autorización, sus actores/fechas originales,
  y la reversión posterior. Lecturas en segundo plano con selección estable incluso
  al entrar nuevas revisiones. Revisión independiente sin hallazgos materiales pendientes;
  render nativo y recorrido visual integral todavía no acreditados.
  Registros y diagnóstico reforzados: cabeceras completas, JSON textual y token Broker
  configurado en memoria; exportación de líneas completas sin reescribir logs. Errores
  YAML con causa/posición sin snippets en evento/sidecar/traceback; original conservado.
  Actividad de workflows con avisos agregados, número de citas sin respaldo y código
  permitido de fallback; texto/URLs remotos no se duplican en estos eventos nuevos.
  Inventario `Delivery_Acceptance_Audit.md`: 65 entregas de fase, 16 criterios globales,
  objetivos, contratos/campos, rutas, guardas y gates con evidencia y pendientes.
  Guarda de fecha sola verificada: evidencia antigua, observación posterior sin cambio
  e inferencia por fecha sin cita no autorizan reemplazo, incluso con política aprobada,
  avance del reloj de planificación y reinicio. Notas, claims e histórico conservados.
  Cliente Broker sanea errores HTTP/de conexión y objetos de error antes de persistirlos,
  usando credenciales de la petición y configuración vigente. Pruebas de rotación,
  persistencia semántica/workflow y reintento; sin reescribir históricos ni resultados.
  Publicación inicial sin sustituir destinos ocupados: conflicto durable y recuperación
  que conserva la edición humana y continúa otras notas. Prueba con escritor separado
  en la carrera de instalación y caída con enlace residual. Requiere volumen con enlaces
  duros; no cierra la ventana check/replace de mantenimiento de notas existentes.
  Puente Obsidian integrado para el entorno confirmado por el usuario: Windows
  con bóveda local. Aprobación, recuperación y reversión usan el cliente; retirada
  la ruta de reemplazo directo. Sin puente, la intención queda pendiente; un conflicto
  de base/recibo requiere revisión. Ajustes permite guardar y comprobar conexión,
  con credencial DPAPI propia ligada a la bóveda. API devuelve 503 y estado pendiente.
  Batería general: 440 pruebas en 293,853 s (435 pasan, cinco omisiones Tcl/Tk).
  Después se añadió y verificó el caso API 503, dentro de diez pruebas focalizadas de
  conexión/integración. Diez pruebas Node pasan; Ruff/mypy pasan (149 archivos).
  Verificación final de API, integración y reversión: 40 casos pasan en 29,873 s,
  después de añadir el aviso API 503 y el mensaje de reversión pendiente.
  Evidencia en `Phase_14_Automation_Governance.md`.

## Límites y evidencia pendiente

- Auditoría inicial de los veinte escenarios en `Acceptance_Evidence.md`: caso 18
  cubierto por pruebas locales de fuente adversaria; resistencia de un modelo real
  pendiente. Explicación de elegibilidad corregida para propuestas nuevas y contextualizada
  sin reescribir snapshots históricos. Matriz de entregables/globales creada en
  `Delivery_Acceptance_Audit.md`; los requisitos parciales y checkpoints visuales siguen
  abiertos. Campos/categorías/reconstrucción documentados con pruebas;
  acceso a versiones/tareas/modelos/decisiones implementado en interfaz, con render y
  recorrido integral pendientes. Saneamiento de logs/ZIP y errores YAML reforzado;
  mensajes remotos persistidos por otras rutas anteriores y texto libre arbitrario
  aún no tienen una garantía global de anonimización.
  La prueba dedicada de fecha como único disparador pasa. El ensayo con otro proceso
  reprodujo sobrescritura después del último hash en el antiguo método de mantenimiento
  y reversión. Ese método se ha sustituido por el puente Obsidian. Bloqueos nativos simples no
  proporcionan aún una solución acreditada; TxF devolvió WinError 6832 al abrir el
  temporal del ensayo. Véase `Note_Replacement_Coordination.md`; el usuario confirmó
  Obsidian/Windows/local. La integración se verifica con un editor de ensayo explícito;
  falta instalar y probar el puente dentro de Obsidian. Este gate no está superado.
  Se preparó una bóveda temporal con cinco notas ficticias y el puente desactivado.
  Computer Use responde, pero rechazó abrir Obsidian: `Computer Use was not approved
  to use Obsidian`, también después de la autorización expresa del usuario para usar
  Obsidian y la bóveda de ensayo. Acceso efectivo pendiente; ejecución real sin acreditar. Evidencia
  y ubicación del ensayo en `Obsidian_Trial_Checkpoint.md`.

- Hay Web y RSS/Atom; no hay rastreo recursivo, GitHub releases ni búsqueda web autónoma.
- La evolución por fases 9–14 está en curso: fases 9 y 10 superan sus checkpoints locales;
  fase 11 verifica núcleo/API/recuperación, con pantalla y red pendientes por entorno.
  La fase 12 supera núcleo/API: 231 pruebas, 230 pasan y una omisión Tcl/Tk; ruff/mypy pasan.
  Primer incremento de fase 13: 236 pruebas, 234 pasan y dos omisiones Tcl/Tk; ruff/mypy
  pasan (110 archivos). El explorador está implementado; su render sigue sin verificar.
  Revisión por lotes: batería actual de 261 pruebas (258 pasan y tres omisiones Tk),
  ruff/mypy pasan (116 archivos). Detalle en `Phase_13_Knowledge_Operations_UI.md`.
  Centro de operaciones, revisión por lotes y estado API/automatizaciones en UI implementados;
  API/UI de reversión implementadas; checkpoints visuales y verificaciones externas siguen pendientes según
  `Knowledge_Lifecycle_Plan.md`.
- La descarga pública devuelve NETWORK_DENIED. La prueba visual de Fuentes no se ejecuta
  porque Tcl/Tk no inicializa init.tcl en este entorno. Véase `Phase_11_Source_Monitoring.md`.
- La consulta real al Broker desde el entorno de desarrollo está sin verificar: el socket
  saliente devuelve WinError 10013 antes de recibir HTTP. La API local sí pasó prueba HTTP.
- Sustituir conocimiento requiere revisión humana o autorización de una política
  aprobada y revalidada; `manual_lock` lo impide siempre. El planificador periódico
  respeta la pausa global y las políticas desactivadas por defecto. No se han autorizado
  políticas en los datos del usuario. La pausa evita nuevas intenciones; las iniciadas
  conservan su finalización/recuperación.
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
