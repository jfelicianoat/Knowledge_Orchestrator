# Reversión conservadora de mantenimiento

La reversión compensa una actualización aplicada; no elimina esa actualización, su
política, sus recibos ni las revisiones de conocimiento. Es una decisión humana
separada de la autoaprobación. El control global pausado no impide esta recuperación
explícita y no se devuelve cupo a una política por haber revertido su publicación.

## Estado de entrega

Implementados el servicio de dominio, planes durables, confirmación, publicación,
reservas y recuperación al arrancar, con migración aditiva 021. La API y la pantalla
**Revisión → Publicaciones y reversión** permiten preparar, confirmar y consultar
recibos. La lógica está probada; el render nativo sigue pendiente por Tcl/Tk.
No se han revertido documentos del usuario.

## Revisión desde la aplicación

Selecciona una publicación aplicada y pulsa **Preparar nueva vista previa**. Compara
el texto completo antes/después y revisa evidencia y estado que se restablecería.
**Confirmar reversión** solicita confirmación humana y un motivo; decide sobre el
plan/hash mostrado, revalidándolo en el servicio. Las acciones esperan a que termine
la recuperación inicial. Publicaciones e historial se consultan en páginas de 100;
un error conserva la página anterior y permite reintentar sin saltarse resultados.
El contenido admite desplazamiento y las acciones permanecen al pie de la pantalla.

El historial local permite auditar vistas previas y decisiones de todos los actores,
incluidos consumidores API. Los planes de otros consumidores son de solo consulta:
la aplicación confirma exclusivamente planes creados desde ella. Preparar una nueva
vista previa crea un plan propio; una reversión ya iniciada/aplicada bloquea otra.

Si se pierde una respuesta de confirmación, **Actualizar recibo** recupera el resultado
durable antes de permitir otra decisión. Una lectura fallida también deshabilita la
confirmación anterior hasta recargarla. APPLYING interrumpido se recupera al reiniciar.
Las operaciones de almacenamiento se ejecutan fuera del hilo de la interfaz.

## API de revisión

Las cinco rutas requieren permiso `review`; `read` y `governance` no lo sustituyen.
Todos los paths siguientes usan el prefijo `/api/v1`; los POST requieren
`Idempotency-Key`. El actor se deriva de la credencial, nunca del cuerpo.

- `GET /review-publications?limit=100&offset=0`: publicaciones aplicadas y estado de
  compensación; no incluye planes ni motivos de otros consumidores.
- `GET /review-reversions?candidate_id=1&limit=100&offset=0`: historial propio;
  `candidate_id` es opcional.
- `POST /review-reversions/preview`: cuerpo `{"candidate_id":1,"expected_revision":1}`;
  devuelve 200 con el plan y Location. Una clave repetida conserva el plan original.
- `GET /review-reversions/{reversion_id}`: plan y recibo propios.
- `POST /review-reversions/{reversion_id}/confirm`: cuerpo con `expected_plan_hash`
  y `reason` (1–2000 caracteres); devuelve 200 al terminar. La idempotencia de la
  confirmación se vincula al identificador de plan, hash y motivo; una clave de
  cabecera nueva no autoriza otra compensación.

Un recibo ajeno devuelve 404. Hash/revisión obsoletos o precondiciones incumplidas
producen conflicto; los errores internos se sanean. Ante respuesta perdida se debe
consultar el recibo, que puede estar aplicado aunque el cliente no recibiera éxito.
La representación compartida con la UI incluye textos, estados, hashes, identificadores
y evidencia; omite rutas de archivos y filas internas del plan persistido.

## Qué se puede revertir

Una propuesta debe estar aplicada y conservar su sucesor, patch, revisión anterior
y evidencia verificable. El texto actual y el registro documental deben corresponder
exactamente a su resultado. No se restaura sobre publicaciones posteriores ni sobre
cambios externos, aunque parezcan pequeños: la comprobación incluye los bytes y los
saltos de línea. Los planes admiten hasta 8 MiB.

La reversión se rechaza si hay `manual_lock` en la nota o en los antecedentes de la
evidencia restaurada, decisiones posteriores sobre los claims afectados,
contradicciones pendientes, claims solapados o conocimiento activo derivado de esa nota.
No se propagan reversiones en cascada. Una publicación pendiente que use sus notas
también impide iniciar la operación. Estos casos necesitan una propuesta de revisión
adaptada al estado actual.

En una nota con otras afirmaciones, se comprueba que sus citas se conservan y se
recalculan sus posiciones. La reversión puede usar tanto una revisión completa como
el histórico estructurado de Estado actual/Histórico: siempre restaura el contenido
exacto anterior y conserva un snapshot del contenido que acaba de retirar.

## Plan y decisión

`MaintenanceReversionService.preview` recibe propuesta, revisión esperada, actor y
clave idempotente. Conserva un plan inmutable con antes/propuesto, hashes, claims,
revisiones, evidencia y notas implicadas. Repetir la misma solicitud devuelve su
plan original, incluso si el entorno cambió; no constituye una nueva validación.
Las solicitudes y lecturas API se separan por actor; la auditoría local puede consultar
todos los actores sin adquirir permiso para confirmar sus planes.

`confirm` exige el identificador del plan, su hash revisado, el mismo actor y un
motivo explícito. Revalida documentos y estado, guarda el snapshot y reserva las
notas en una transacción SQLite antes de escribir. Otro plan o una repetición
concurrente no puede iniciar una segunda reversión de la misma propuesta.
Una confirmación ya aplicada se devuelve idempotentemente con el mismo motivo.

Las reservas impiden nuevas publicaciones, extracciones o cambios de estado/bloqueo
en las notas implicadas. Las consultas CURRENT excluyen temporalmente esas notas y
la procedencia reservada. La aplicación reutiliza el reemplazo atómico y el control
de hash existente; una diferencia detectada queda en CONFLICT.

## Vigencia e histórico

El claim anterior se restablece en una **nueva revisión y un nuevo período de vigencia**,
con el estado revisable que tenía antes de la actualización. No se modifica su
historial anterior. Por ejemplo, su historial puede mostrar
CURRENT → SUPERSEDED → CURRENT, con las fechas y actores de cada decisión.
Esto no equivale a verificar una afirmación por restaurar un archivo.

El sucesor retirado pasa a HISTORICAL/RETRACTED y enlaza con el claim restablecido.
La sucesión anterior sigue registrada en el historial inmutable. Se conservan citas,
fuentes, entidades, embeddings y procedencia de ambos. Una proyección restaurada
mantiene su vínculo a la evidencia original; no se fabrica una fuente nueva.
La búsqueda y las consultas temporales utilizan los estados actualizados.

El candidato original permanece APPLIED y su ejecución automática conserva su
recibo de publicación: ambos describen un hecho que ocurrió. El registro separado
de reversión identifica la compensación y su responsable. Los candidatos pendientes
dirigidos al sucesor retirado quedan en conflicto; no se reabren automáticamente
propuestas históricas.

## Recuperación y límites

PREVIEW no modifica notas. APPLYING identifica una confirmación durable; APPLIED
acredita la compensación finalizada y CONFLICT exige revisión. El runtime recupera
las reversiones después del mantenimiento semántico y antes de la reconciliación y
el arranque de workers.

Si el proceso cae antes de sustituir el archivo, se revalidan y aplican los mismos
bytes. Si cae después de sustituirlo y antes del commit SQLite, el hash permite
terminar el registro sin duplicar revisiones ni historia. Un error SQLite mantiene
la intención para recuperación. Una edición externa nunca se sobrescribe para
forzar el cierre de un recibo; se registra conflicto y se excluye el conocimiento
afectado de CURRENT hasta reconciliarlo.

No existe una transacción distribuida entre el editor externo, NTFS y SQLite.
Se comprueba el hash antes y después del reemplazo y se reconcilia cualquier
diferencia observada. Como en la publicación existente, debe ejecutarse un único
runtime sobre cada raíz de datos.

## Evidencia

`tests/test_maintenance_reversion.py`: 19 pruebas pasan en 40,689 s. Cubren
restauración e intervalos, revisiones y recibos intactos, aislamiento/idempotencia,
planes inmutables, confirmación exacta, cambios externos, `manual_lock`, decisiones
posteriores, caídas antes/después del reemplazo, reservas, confirmación concurrente,
fallo SQLite, conflicto durante aplicación, claims no afectados, dependencias,
publicaciones posteriores, snapshot dañado, recuperación integrada al runtime y
desplazamiento de citas repetidas sin colisiones transitorias.

Los ensayos usan notas y bases temporales. No acreditan validación visual ni una
prueba real del Broker; esas verificaciones siguen pendientes.

API/UI añaden 17 pruebas: 16 pasan y una omisión Tcl/Tk, en 15,554 s. Incluyen
confirmación por HTTP real de loopback, aislamiento, schemas, respuestas perdidas,
cancelación, lectura incierta, auditoría local, paginación fallida y foco de teclado.
La revisión independiente de código termina sin correcciones pendientes; no acredita render.

Batería completa final del séptimo incremento: **366 pruebas en 169,196 s; 361 pasan
y cinco omisiones Tcl/Tk**. Ruff/mypy pasan sobre 142 archivos y `diff --check` no informa errores.
