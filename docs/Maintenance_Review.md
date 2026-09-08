# Revisión y mantenimiento del conocimiento

Cada cambio semántico genera una propuesta antes de modificar una nota. El detalle
conserva ambas afirmaciones y citas, entidades, fuentes y confianza configurada,
relación, justificación resumida, impacto, notas/claims afectados, transformación,
histórico previsto, riesgos y tareas/modelos declarados por el Broker. No contiene
razonamiento privado del modelo. Confianza y consenso no equivalen a verificación factual.

## Evidencia y procedencia

La evidencia exacta pertenece a la **nota publicada** por el workflow. Esa nota puede
ser un resumen generado por IA: la coincidencia literal demuestra respaldo documental
local, no verificación independiente contra el documento original ni verdad factual.
El claim conserva la captura de origen, la nota y el hash de su evidencia. Las fuentes
monitorizadas añaden la configuración/trust vigente en la observación, obtenida del
recibo durable de ingesta; una etiqueta dentro del contenido no puede atribuir confianza.
Si la captura no coincide con ese recibo, se muestra una advertencia y se retira el trust.

Una aplicación crea un claim sucesor **en la nota modificada**, derivado del claim
testigo en la nota fuente. Ambos pueden existir como CURRENT en sus respectivos
documentos; representan instancias documentales de la misma evidencia, no dos fuentes
independientes. `derived_from_claim_id` conserva esa dependencia. La evidencia clonada
sigue apuntando a la nota/captura original. La reextracción no la atribuye a la captura
antigua de la nota destino ni resucita texto del histórico controlado.

Si un antecesor deja de estar vigente o su nota pierde coherencia, las consultas CURRENT
excluyen las proyecciones dependientes. La reconciliación las marca REVIEW_REQUIRED,
con auditoría, salvo manual_lock o aplicación pendiente. Un bloqueo conserva el estado
registrado, pero no obliga a servir como vigente una evidencia incoherente.

## Decisiones individuales

La primera evaluación tiene `proposal_revision=1`; las ediciones generan versiones
inmutables. El revisor envía la revisión que abrió. Una revisión obsoleta devuelve
conflicto y no aplica su decisión a una propuesta distinta. Los candidatos antiguos sin
evaluación se regeneran mediante edición con revisión 0. Las intenciones ya aprobadas
antes de la migración conservan su recuperación compatible.

- **Editar:** cambia relación, justificación y propuesta dentro del contrato de evidencia.
  El reemplazo debe conservar literalmente la cita nueva; no acepta hechos añadidos.
- **Aprobar:** valida revisión, bloqueo, ambos hashes y spans, conflictos y dependencias;
  guarda intención y snapshot antes de publicar; reindexa el sucesor y conserva historia.
- **Rechazar:** registra actor/motivo sin cambiar la nota. No declara verdadero o falso
  ninguno de los claims disputados y no cancela una aplicación ya iniciada.
- **Revisar vigencia:** decisión separada, con revisión optimista y motivo, para CURRENT,
  DISPUTED, UNCERTAIN o REVIEW_REQUIRED. No reactiva histórico ni sustituye una publicación.

CONTRADICTS deja ambos claims desbloqueados DISPUTED; UNCERTAIN marca el nuevo como incierto.
Una contradicción abierta también excluye de CURRENT un claim bloqueado sin modificarlo.
Las contradicciones entre fuentes oficiales o de confianza desigual requieren revisión
humana. Aprobar una resolución conserva la formulación anterior como HISTORICAL;
SUPERSEDES registra SUPERSEDED. Rechazar no elimina la discrepancia registrada.

## Publicación e histórico

Una nota sencilla con un párrafo aislado puede dividirse de forma determinista en
«Estado actual» e «Histórico». Una nota que ya tiene esas secciones controladas agrega
la versión anterior al histórico existente. Si hay estructura ambigua, tablas, listas
o varios párrafos, se reemplaza únicamente el span y se conserva la revisión completa.
Un claim activo solapado impide esa aplicación individual. Los claims no solapados
conservan estado y ajustan offsets cuando cambia la longitud del texto.

La intención durable reserva la nota destino y toda la cadena de evidencia frente a
otras aplicaciones y cambios de estado/bloqueo internos. Una interrupción después de
reemplazar la nota completa la transacción pendiente sin crear otro sucesor. Una
interrupción anterior revalida evidencia y base antes de continuar. Ediciones externas
producen CONFLICT y se conservan. Existe una ventana mínima entre comprobar el archivo
y reemplazarlo: no se afirma atomicidad distribuida con editores externos.

## Evaluar una propuesta con una política

En Revisión, selecciona una propuesta y pulsa **Evaluar con política**. Se abre
**Servicios → Automatizaciones → Políticas y decisiones**, conservando el identificador
y la revisión exactos. Elige una política, revisa sus condiciones y pulsa **Simular
propuesta**. Los cambios del formulario deben guardarse antes; la simulación no publica.
**Quitar filtro de propuesta** permite volver a simular páginas del ámbito completo.

Los assessments nuevos incluyen `policy_evaluated=false`, `publication_authorized=false`
y `POLICY_EVALUATION_REQUIRED`. Su `eligible=false` indica que la propuesta por sí sola
no acredita autoaprobación; la elegibilidad frente a una política se obtiene en la
simulación. Los snapshots antiguos conservan literalmente `NO_APPROVED_POLICY` si se
generaron así. El detalle añade `automation_review` como explicación actual separada,
sin reescribir ese histórico ni inferir ausencia de políticas.

Leer una simulación histórica muestra sus propias propuestas y revisiones. Con filtro
activo, un registro de otra propuesta o revisión no permite autorizar. La autorización
explícita habilita futuras propuestas que cumplan la política; reanudar el control
global requiere otra decisión. Véase [Automation_Governance.md](Automation_Governance.md).

## Consultar trazabilidad y versiones

Selecciona una propuesta en **Revisión**, o una entrada en **Cambios y actividad →
Propuestas / Histórico de decisiones**, y pulsa **Ver trazabilidad**. La consulta
conserva esa propuesta aunque cambie la selección en la ventana principal.

- **Versión de propuesta** recorre páginas de 100 revisiones, con fecha y autor.
- **Comparación** muestra la evidencia anterior y el reemplazo de la revisión elegida.
- **Evidencia y análisis** identifica las capturas, fuentes vigiladas, confianza
  configurada, cambios y tareas/modelos que constaban al guardar esa revisión.
- **Decisión y publicación** muestra la decisión actual de la propuesta, sus fechas,
  lote o política/ejecución, versión anterior conservada y reversión si existe.

La revisión histórica y la decisión actual se identifican por separado. Los modelos
son los reportados por el Broker; cuando no hay dato, la pantalla lo dice. Una
publicación que fue revertida sigue conservando su recibo original y se señala la
reversión. La consulta no afirma vigencia actual ni permite aplicar cambios.

Las lecturas se ejecutan en segundo plano. Ante fallo se conserva el contenido y
la etiqueta de la última lectura correcta; **Reintentar** repite la consulta pendiente.
Si llegan nuevas versiones, la página se recoloca para conservar la revisión elegida.
La simulación usada para ejecutar se distingue de la revisada al autorizar la política,
con el actor y la fecha originales de esa autorización; el historial antiguo sin ese
vínculo se indica expresamente.
Los textos muy grandes se abrevian de forma explícita. Los recibos completos y la
nota anterior se consultan en los apartados indicados por la propia vista.
