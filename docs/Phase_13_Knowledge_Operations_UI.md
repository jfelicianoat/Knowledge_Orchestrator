# Fase 13 — Centro de operaciones (en curso)

Ampliación del 8-sep-2026: **Ver trazabilidad** en Revisión y Propuestas/Histórico
permite recorrer versiones, comparación, fuentes, tareas/modelos y decisiones de
publicación/reversión. Revisión independiente del incremento sin hallazgos pendientes;
pruebas locales verificadas. Render y recorrido visual integral siguen abiertos por
Tcl/Tk. Registro detallado: duodécimo incremento de `Phase_14_Automation_Governance.md`.

1. **Estado encontrado.** Tkinter/ttk ya ofrece navegación, listas maestro-detalle,
   selección persistente, fuentes, revisión individual y puente de eventos. Faltan
   exploración de claims/entidades/vigencia, pipeline integral, revisión masiva,
   comparación paralela, histórico transversal y operación API/automatizaciones.
2. **Diseño propuesto.** Conservar Tkinter y el lenguaje grafito/cian/Segoe UI existente.
   Es suficiente para listas filtradas, paneles redimensionables y revisión por lotes.
   Limitaciones: accesibilidad/renderizado dependientes de Tcl/Tk, navegación horizontal
   estrecha, gráficos complejos y trabajo lento en callbacks. Una migración web exigiría
   nuevo empaquetado, servidor y contratos de sesión: coste/riesgo innecesarios para
   estas funciones. No se cambia framework. Modo Operate; extender la interfaz aprobada.
3. **Cambios previstos.** Primero lectura del conocimiento con filtros de estado y
   entidad/texto, evidencia e histórico; después pipeline navegable, cambios y actividad;
   revisión antes/propuesto, preview y ejecución masiva por tarea; API y automatización.
4. **Archivos.** `ui/operations_snapshots.py`, `ui/dashboard/conocimiento.py`, ensamblaje
   del dashboard; futuras vistas de operaciones/revisión y servicio de lotes; pruebas
   de snapshots, servicios y widgets; documentación de funcionamiento y checkpoint.
5. **Migraciones.** El explorador no necesita migración. La ejecución masiva requerirá
   recibo durable y revisión por tarea para recuperación y resultados parciales.
6. **Tests previstos.** Filtros current/history/review, entidades, búsquedas, selección
   estable, estados vacíos, navegación, cambios externos, lotes mixtos y reinicio.
7. **Verificación.** Primer incremento: 236 tests en 49,792 s; **234 pasan y dos se
   omiten por init.tcl** (Fuentes y Conocimiento). Ruff pasa y mypy pasa (110 archivos).
   `git diff --check` pasa. Cuatro pruebas nuevas de snapshots/reconciliación pasan;
   la quinta, sobre widgets, requiere Tcl/Tk. No se afirma verificación del render.
8. **Riesgos/deuda.** Tcl/Tk no inicializaba init.tcl en el entorno anterior; el checkpoint
   visual no está demostrado. No confundir snapshots SQL con comprobación del render.
   No presentar un listener API activo por haber registrado solicitudes antiguas.
9. **Checkpoint.** Abierto; no comenzar gobernanza como completada antes de demostrar
   interfaz/acciones masivas. Las limitaciones externas seguirán etiquetadas.
10. **Próximo paso.** Construir y comprobar el explorador integrado reutilizando filtros
    de vigencia del núcleo, sin duplicar una definición diferente de CURRENT en la UI.

## Primer incremento implementado

- Explorador integrado: estados vigente/histórico/en revisión/todos, búsqueda de
  entidad/texto, paginación, evidencia, fuentes, historial de decisiones y sucesión.
- La carga contrasta archivos y reconciliación en un worker único, sin tocar widgets
  desde ese hilo. Las respuestas obsoletas se descartan si cambiaron los filtros.
- El refresco conserva selección por identificador y no reescribe texto idéntico,
  evitando perder la posición y selección de lectura. Una selección oculta se limpia.
- Texto en edición y consulta confirmada se separan. Buscar reinicia la paginación;
  el desplazamiento se ajusta si el total disminuye. Ctrl+F conserva la pantalla actual.
- La cabecera existente separa marca y navegación en dos filas para incluir Conocimiento.
  Se conserva biblioteca documental, resto de vistas, colores y componentes existentes.
- La revisión independiente de Impeccable detectó cuatro defectos de coherencia,
  refresco, paginación y atajo de teclado; se corrigieron. El revisor confirmó el mismo
  impedimento Tcl/Tk y no pudo evaluar el render a 1080×680 o 1440×900.
- Archivos concretos: `ui/operations_snapshots.py`, `ui/dashboard/conocimiento.py`,
  `ui/dashboard/__init__.py`, `tests/test_phase_thirteen_operations_ui.py`. Sin migración.

## Segundo incremento — 6 de septiembre de 2026

1. **Estado encontrado.** El explorador funcionaba localmente, pero cada fuente tenía
   su lista aislada; no había una vista transversal de análisis, propuestas y decisiones.
2. **Diseño.** Extender el resumen con seis etapas navegables y añadir Operaciones con
   filtros por etapa/estado. Reutilizar las pantallas de fuente, documento y revisión.
3. **Cambios.** Pipeline Fuentes → Cambios → Análisis → Propuestas → Revisión → Publicación;
   listas acotadas y paginadas de novedades/análisis/propuestas/histórico/actividad;
   trazabilidad de novedad a captura, notas y propuestas; incorporación controlada;
   acceso al documento/fuente/revisión y consulta de versiones anteriores conservadas.
   Los conflictos aparecen ahora en Revisión y pueden editarse/regenerarse.
4. **Archivos.** `ui/dashboard/operaciones.py`, `operations_snapshots.py`, `inicio.py`,
   ensamblaje del dashboard, `revision.py`, `ui/snapshots.py` y tests de fase 13.
5. **Migraciones.** Ninguna; todas las lecturas y acciones usan registros/servicios existentes.
6. **Tests.** Ocho escenarios propios de fase 13: siete pasan y uno requiere Tk.
   Comprueban trazabilidad fuente → captura → nota → propuesta → revisión, filtros,
   errores de análisis, paginación, contadores y ausencia de prompts/resultados privados.
   La prueba de widgets también comprueba la persistencia de la lectura histórica y
   navegación a documentos con una búsqueda previa que los excluía.
7. **Verificaciones.** Batería completa actual: **248 tests en 52,282 s, 246 pasan y
   dos omisiones explícitas por Tcl/Tk**. Ruff pasa; mypy pasa (111 archivos).
   La batería incluye mejoras concurrentes del contrato Broker 2.10, conservadas.
8. **Riesgos/deuda.** NO VERIFICADO: render y uso real a 1080×680/1440×900; Broker y
   conectores en red. Las pruebas SQL y los workers de lectura no acreditan el render.
   El histórico de decisiones muestra aplicadas/descartadas; las publicaciones enlazan
   la biblioteca. Los indicadores de vigencia reconcilian archivos en segundo plano.
9. **Checkpoint.** Incremento local verificado. Revisión independiente detectó y se
   corrigieron lectura histórica reemplazada por refresco, búsqueda heredada al abrir
   documento, conflictos sin acceso a revisión y contador/listado de propuestas dispares.
   El checkpoint integral de fase 13 sigue abierto.
10. **Próximo paso.** Comparación antes/propuesto y aprobación masiva durable con preview,
    seguidas del estado API/automatizaciones. Gobernanza de fase 14 pendiente.

## Diseño del siguiente incremento: revisión masiva

- Compartir los mismos guardas de aplicación entre preview y aprobación individual:
  revisión, bloqueos, hashes de objetivo/evidencia, solapamientos y dependencias.
  La vista previa no crea intenciones de publicación ni modifica notas.
- Guardar un plan de lote y sus ítems/revisiones. La selección explícita y «todas las
  elegibles» deben congelar el conjunto que el usuario revisó; no añadir propuestas que
  aparezcan después. Informar tareas, claims y notas únicos, acciones y no elegibles.
- Tras confirmación de ese plan, registrar actor e intención durable. Aplicar cada ítem
  con el servicio individual y su revisión fijada; revalidar justo antes de cada escritura.
  Registrar éxito, conflicto, omisión o fallo por tarea. Un fallo no revierte éxitos ajenos.
- Recuperar después de una caída usando el estado de candidato/intención existente;
  un sucesor ya materializado no se duplica aunque falte el recibo del ítem del lote.
  Una intención ambigua permanece pendiente hasta reconciliación, sin inventar éxito.
- Un lote no es una política de autoaprobación. Ningún valor de confianza autoriza por
  sí solo cambios. Las políticas de fase 14 seguirán explícitas, versionadas y apagadas
  por defecto; reutilizarán elegibilidad y auditoría, sin ignorar manual_lock.

## Tercer incremento: revisión individual y masiva durable

1. **Estado encontrado.** La aprobación era individual y síncrona en Tk. No había plan
   de selección conservado ni recibo recuperable por tarea. Dos lectores concurrentes
   podían intentar tomar una misma aplicación; una validación tardía podía marcar el
   candidato en conflicto mientras otra petición conservaba una intención viva.
2. **Diseño.** Compartir guardas entre preview y aplicación, fijar el conjunto/revisiones
   del lote, confirmar su hash con actor y ejecutar en un worker independiente del Broker.
   La atomicidad es por tarea y el lote conserva resultados parciales.
3. **Cambios.** Planes inmutables con antes/después, fuentes, riesgos y recuentos; selección,
   todas las pendientes, confirmación explícita y recibos; API autenticada con aislamiento
   de consumidor; recuperación de recibos después de recuperar publicaciones; estado
   visible RECOVERY_REQUIRED. UI con comparación en dos paneles, selección múltiple
   preservada al refrescar e historial paginado. Lecturas de archivos y ejecución fuera
   de Tk. La aprobación individual usa ahora la misma vista previa de un único elemento.
4. **Archivos.** `review_batch_repository.py`, `review_batches.py`, `review_worker.py`,
   `review_batch_dialog.py`, `application_guards.py`, runtime, repositorio/servicio
   semántico, modelos, API, `dashboard/revision.py`, pruebas y documentación.
5. **Migraciones.** Aditiva 016: planes, ítems, vínculo de candidato a lote, índices y
   triggers que impiden modificar el plan o las identidades/revisiones seleccionadas.
   No modifica notas ni borra histórico al migrar.
6. **Tests.** Trece escenarios nuevos: vista previa sin publicación, idempotencia,
   integridad del plan, permisos/propiedad, selección congelada, resultados parciales,
   bloqueos manuales, revisión obsoleta, colisiones entre notas, aprobación concurrente,
   caídas antes/después de aplicar, recuperación ordenada y worker sin Broker. Uno
   comprueba widgets/selección y omite únicamente si falta el entorno Tcl/Tk.
7. **Verificaciones.** Primer recorrido completo: 258 pruebas en 62,959 s, 256 pasan y
   dos omisiones Tk. Tras añadir recuperación visible y pruebas del worker/widgets:
   13 pruebas específicas en 9,722 s, 12 pasan y una omisión Tk. Ruff pasa y mypy pasa
   en 116 archivos. Resultado completo final del incremento se registra debajo.
8. **Riesgos/deuda.** Render real aún NO VERIFICADO. Broker/conectores reales siguen
   pendientes por denegación de red. Un runtime por directorio; la recuperación de
   lotes se llama al arrancar antes de workers, nunca sobre escrituras vivas. Límite
   explícito de 1000 propuestas/8 MiB; las dependencias mutuas requieren revisión
   separada. La fase 14 todavía no habilita ni configura autoaprobación.
9. **Checkpoint.** Revisión independiente de código detectó navegación de historial
   bloqueada por sondeo continuo y detalles de lote anterior persistentes. Corregidos
   con pausa entre consultas, controles de navegación durante lectura y limpieza al
   cambiar de lote/página. El checkpoint visual e integral de fase 13 sigue abierto.
10. **Próximo paso.** Estado API y automatizaciones en UI, gobernanza de fase 14 y
    verificación real de pantalla y flujo externo cuando el entorno lo permita.

### Verificación final del tercer incremento

- Batería completa: **261 pruebas en 67,990 s; 258 pasan y tres omisiones explícitas
  por Tcl/Tk** (Fuentes, Operaciones/Conocimiento y diálogo de lotes).
- Ruff sin incidencias; mypy sin incidencias en 116 archivos; diff sin errores de espacios.
- El revisor independiente volvió a comprobar las dos correcciones y no detectó
  regresiones directas. Es revisión de código, no verificación del render.
- El incremento local de revisión por lotes queda verificado con estos límites.
  No se declara completa la fase 13 ni el objetivo global.

## Cuarto incremento: estado de API y procesos automáticos

1. **Estado encontrado.** La API se iniciaba solo por CLI; la ventana no podía saber
   si su propia sesión atendía peticiones ni qué consumidores usaban el conocimiento.
   La vigilancia y los lotes confirmados funcionaban, sin vista común de sus procesos.
2. **Diseño.** Controller de listener local por runtime; estado observado de su hilo y
   socket, consumidores saneados y actividad acotada. Añadir Servicios con pestañas de
   API y automatizaciones, reutilizando las pantallas de fuentes, análisis y lotes.
3. **Cambios.** Iniciar/detener API en loopback, copiar dirección sin token, ver permisos,
   consumidores actuales/anteriores y peticiones con errores. Recargar credenciales solo
   al reiniciar listener. Estado de workers, fuentes, análisis, lotes y recuperación.
   La autoaprobación se indica explícitamente como desactivada y pendiente de fase 14.
4. **Archivos.** `api/server.py`, runtime, `services/operations_status.py`,
   `ui/dashboard/servicios.py`, ensamblaje del dashboard y propiedades de workers;
   `tests/test_operations_status.py` y prueba de widgets de fase 13.
5. **Migraciones.** Ninguna. La vista usa eventos ya existentes y estado de este proceso.
6. **Tests.** Seis nuevos casos: estado sin listener, HTTP real de loopback 200/401/403,
   cierre/reinicio, credenciales fijas mientras atiende, puerto ocupado, configuración
   inválida, historial acotado y ausencia de credenciales/cuerpos/URLs no reconocidas.
   El caso de widgets de fase 13 también inspecciona las nuevas pestañas.
7. **Verificaciones.** 14 pruebas de servicios/operaciones en 8,373 s: 13 pasan y una
   omisión por Tcl/Tk. Ruff pasa; mypy pasa en 118 archivos. El cierre de un puerto en
   Windows puede dar ConnectError o ConnectTimeout; se admiten ambas respuestas sin
   considerarlas una petición HTTP exitosa. Batería completa final registrada debajo.
8. **Riesgos/deuda.** El listener observado pertenece a esta sesión, no detecta otros
   procesos. Recuentos sobre las últimas 1000 peticiones válidas, mostradas de 100 en 100.
   Credenciales desde KO_API_CLIENTS; no se muestran tokens ni se añaden secretos a disco.
   Render real pendiente. Revisión independiente de este incremento no ejecutada por
   límite de uso del agente; no se atribuye a las pruebas locales ese checkpoint.
9. **Checkpoint.** HTTP local y núcleo verificados; checkpoint visual e independiente
   todavía abierto. El Broker y los conectores externos no quedan validados por loopback.
10. **Próximo paso.** Fase 14: políticas versionadas, simulación, límites, interruptor de
    emergencia, ejecución con autorización revalidada y auditoría. Mantener desactivadas
    las políticas hasta una decisión humana explícita.

Verificación completa del cuarto incremento: **267 pruebas en 53,977 s; 264 pasan y
tres omisiones Tcl/Tk**. Ruff/mypy sin incidencias (118 archivos). HTTP real de loopback
verificado; render y revisión independiente de este incremento pendientes por entorno.
