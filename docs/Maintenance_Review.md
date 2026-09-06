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

No hay autoaprobación habilitada. La evaluación guarda `NO_APPROVED_POLICY`; las fases
13–14 incorporarán revisión masiva y políticas explícitas/versionadas con simulación.
