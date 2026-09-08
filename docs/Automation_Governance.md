# Políticas de autoaprobación

El Orchestrator crea políticas desactivadas y mantiene el control global pausado por
defecto. Registrar una política o simularla no publica ni activa cambios. El worker
solo planifica políticas autorizadas cuando el control global está reanudado.

Una fecha antigua en una afirmación o en su evidencia no autoriza una actualización.
El sistema exige una propuesta respaldada por evidencia y las condiciones de la política.
Observar de nuevo el mismo texto en una fecha posterior tampoco permite reemplazarlo.
La vigencia local no equivale a comprobar que la afirmación siga siendo cierta en el
mundo real. Estas guardas se verifican con avance del reloj del planificador y reinicio
en `tests/test_temporal_authorization.py`.

## Uso desde Servicios

Abre **Servicios → Automatizaciones → Políticas y decisiones**. El apartado
**Procesos y estado** conserva el estado de los workers y sus últimas incidencias.

1. Pulsa **Nueva política** y define nombre, fuentes, tipos/roles, relaciones,
   confianza mínima y límites. Las fuentes se muestran en páginas de 100 y la selección
   se conserva al cambiar de página; el ámbito admite hasta 1000 fuentes explícitas.
2. Pulsa **Guardar desactivada**. Una edición de una política existente exige motivo,
   conserva su versión anterior y revoca la autorización.
3. Pulsa **Simular guardada**. La pestaña Simulación permite elegir entre 1 y 100
   propuestas pendientes del ámbito por página. **Simular siguientes** avanza sin
   volver al principio; una página vacía indica que no hay más resultados.
4. Selecciona una propuesta para comparar Antes/Propuesto y revisar evidencia,
   justificación, exclusiones y cupos. La simulación no publica ni reserva cupo.
5. **Autorizar esta versión** exige confirmar las condiciones y escribir un motivo.
   Se autoriza la política para futuras propuestas que las cumplan; la simulación
   revisada queda vinculada a la decisión. Editar el formulario invalida la simulación
   disponible para autorizar hasta guardar y volver a simular.
6. **Reanudar políticas autorizadas** es una decisión separada, con confirmación y
   motivo. **Pausar autoaprobación** sigue disponible durante una simulación pendiente.
   La pausa impide nuevas intenciones; las ya iniciadas pueden terminar o recuperarse.

El estado del control global se consulta aproximadamente cada cinco segundos mientras
el panel está visible, sin sobrescribir cambios sin guardar. **Actualizar estado**
renueva las listas; **Recargar política** obtiene la versión actual y pide confirmar
el descarte si hay cambios locales. Ante una revisión concurrente, recarga y revisa
la política antes de decidir de nuevo. El servidor vuelve a comprobar las revisiones
al registrar cada decisión, aunque la pantalla todavía muestre un estado anterior.

Desde **Revisión → Evaluar con política**, la selección queda limitada a la propuesta
y revisión elegidas. **Simular propuesta** mantiene ese ámbito al cambiar de política;
**Quitar filtro de propuesta** lo retira sin realizar otra simulación. Una revisión
modificada después de seleccionarla se marca como bloqueo; no se sustituye en silencio.
Las simulaciones del historial muestran su propio ámbito. Con el filtro activo, un
registro de otras propuestas o revisiones no habilita **Autorizar esta versión**.
La comparación incluye desplazamiento exterior y altura mínima en ventanas bajas;
las acciones de decisión permanecen fuera del área desplazable.

En **Historial** puedes consultar versiones/decisiones, simulaciones, ejecuciones y
pausas globales, con navegación por páginas y recibos por propuesta. Leer registros
no autoriza publicaciones. Los controles de escritura esperan a que termine la
recuperación inicial de la aplicación; las lecturas y operaciones se ejecutan fuera
del hilo de la interfaz.

Los planes conservan el límite de 8 MiB. Reduce el tamaño de página si una simulación
lo supera; si una sola propuesta lo excede, necesita revisión o división. Los paneles
de texto abrevian contenidos superiores a 200 000 caracteres y lo indican expresamente.
La vista abreviada no sustituye la revisión del documento completo en Conocimiento.

**Verificado:** lógica de formulario, paginación, reintentos, revisiones y pausa
independiente mediante pruebas locales, incluida la selección exacta desde Revisión.
La revisión independiente del décimo incremento y sus correcciones no dejó hallazgos
materiales. **No verificado:** render y flujo de widgets nativos, porque Tcl/Tk no puede
inicializarse en este entorno. Esta revisión no acredita el render de Servicios/políticas.

## Permiso y alcance

Todas las rutas siguientes requieren un consumidor API con el permiso **`governance`**.
Los permisos `read`, `review` y `sources` no lo incluyen. No se añade este permiso
automáticamente a consumidores existentes. La API local, autenticación Bearer y
configuración de consumidores se describen en [Knowledge_API.md](Knowledge_API.md).

`governance` permite administrar todas las políticas y leer su auditoría en este
runtime, incluidos registros creados por otro administrador o por el planificador.
No es un ámbito privado por consumidor. El actor se deriva de la credencial como
`api:<nombre>`; no puede suplantarse enviando `actor` o `approved_by` en el cuerpo.
Las claves idempotentes de creación y simulación sí se separan por consumidor.

## Rutas

Prefijo común: `/api/v1`. Todos los cuerpos son JSON estricto.

| Operación | Método y ruta |
|---|---|
| Registrar/listar políticas | POST /automation/policies · GET /automation/policies |
| Consultar/revisar configuración | GET /automation/policies/{policy_id} · PATCH /automation/policies/{policy_id} |
| Autorizar/desautorizar | PATCH /automation/policies/{policy_id}/activation |
| Historial de versiones/decisiones | GET /automation/policies/{policy_id}/history |
| Última evaluación y próxima comprobación | GET /automation/policies/{policy_id}/schedule |
| Simular configuración | POST /automation/policies/{policy_id}/simulations |
| Listar/consultar simulaciones | GET /automation/simulations · GET /automation/simulations/{simulation_id} |
| Consultar/modificar pausa global | GET /automation/control · PATCH /automation/control |
| Historial de pausa/reanudación | GET /automation/control/history |
| Listar/consultar ejecuciones | GET /automation/runs · GET /automation/runs/{run_id} |

Listados e historiales admiten `limit` (1–1000, predeterminado 100) y `offset`.
Simulaciones y ejecuciones también admiten `policy_id`. Los historiales devuelven
primero lo más reciente. En el historial de una política, la paginación se aplica
por separado a las listas `versions` y `decisions`.

La API devuelve 200 al crear o simular. `Location` identifica el recurso durable.
Los POST requieren `Idempotency-Key` de 8–200 caracteres. Repetir exactamente una
solicitud devuelve su recurso existente; reutilizar la clave con otro cuerpo produce
409. Repetir una simulación conserva el plan original aunque la política haya cambiado:
no equivale a reevaluar ni renovar su autorización. Usar otra clave para una simulación nueva.
Los PATCH requieren revisiones esperadas; repetir una decisión ya aplicada devuelve
409 y no crea otra decisión. Leer el estado actual para reconciliar una respuesta perdida.

## Configurar, revisar y autorizar

1. Registrar una política con `name` y `source_ids` explícitos. Las restantes condiciones
   tienen valores conservadores: fuentes web/RSS oficiales, relación SUPERSEDES,
   claims VERSION, confianza de fuente mínima 80/100, confianza de comparación mínima
   0,95, un claim y una nota por tarea, cinco tareas por ejecución y veinte por día UTC.
   OpenAPI enumera todas las condiciones. La confianza no sustituye evidencia ni elimina
   contradicciones, conflictos o bloqueos.
2. Consultar la configuración y sus `revision` y `state_revision`.
3. Solicitar una simulación enviando `expected_revision`. Opcionalmente incluir
   `selection` con pares `candidate_id`/`expected_revision`; como máximo 1000 propuestas
   y 8 MiB de plan. Sin selección se consideran las propuestas pendientes/revisables
   y se explican las exclusiones por ámbito o elegibilidad.
4. Revisar el plan: configuración, propuestas, antes/después, evidencia, exclusiones,
   cupos previstos y control global. `publication_authorized=false` y
   `limits_reserved=false` significan que esta operación no publica ni reserva cupo.
5. Si se decide autorizar esa versión, enviar PATCH a `/activation` con `enabled=true`,
   `expected_revision`, `expected_state_revision`, un `reason` explícito y
   `reviewed_simulation_id`. Debe corresponder a la misma política, versión, activación
   y revisión del control global. El vínculo a la simulación se conserva en la decisión.
6. Reanudar el control global es una decisión separada: PATCH `/automation/control`
   con `paused=false`, su `expected_revision` y `reason`. No habilita políticas
   desactivadas. Una vez reanudado, el worker puede evaluar las políticas autorizadas.

Para desautorizar se usa la misma ruta `/activation` con `enabled=false`, revisiones
actuales y motivo; no requiere simulación. Para editar, PATCH de la política recibe
`config` completo, ambas revisiones esperadas y motivo. **Toda edición revoca la
autorización**, conserva la versión anterior y exige una nueva revisión/autorización.

## Pausa, ejecución y recuperación

PATCH del control global con `paused=true` impide iniciar nuevas intenciones.
Las intenciones ya reservadas pueden terminar o recuperarse: la pausa no deshace
publicaciones ni elimina revisiones. Pausar y reanudar invalida las autorizaciones
de ejecución fijadas con una revisión anterior del control; el planificador vuelve
a evaluar trabajo nuevo con la revisión actual.

Cada tarea vuelve a comprobar política, fuente, procedencia, evidencia, hash de
nota, `manual_lock`, contradicciones, dependencias y cupos dentro de la transacción
que reserva publicación. El cupo diario se contabiliza por política en UTC y no se
reinicia al editarla; los intentos reservados fallidos también consumen cupo.

Las ejecuciones conservan estados y recibos por propuesta, incluidos resultados
parciales. Las que requieren recuperación quedan detenidas hasta reiniciar el runtime
y reconciliar las intenciones. No ejecutar dos runtimes sobre la misma raíz de datos.

La API no ofrece una operación de publicación directa, borrado de histórico ni
restauración ciega de notas. El servicio de reversión conservadora está implementado;
su acceso y recibos están en la API de revisión y en Revisión → Publicaciones y reversión. Consulta
[Maintenance_Reversion.md](Maintenance_Reversion.md) para sus condiciones y recuperación. Los controles
de políticas, estado de los workers y permisos del consumidor aparecen en Servicios;
la validación visual pendiente se detalla arriba.

## Recuperación de lecturas y navegación

Las páginas de políticas, fuentes e historial solo avanzan después de una lectura
correcta. Si falla, permanecen los registros anteriores, el borrador y su selección;
reintentar solicita la misma página. Al cambiar de política, el selector conserva
la identidad de la política visible hasta cargar la nueva. El historial conserva
juntos su categoría y desplazamiento cuando la lectura falla.

Reintentar «Simular siguientes» después de perder la respuesta conserva la clave
del plan solicitado. Volver a la primera página usa otra identidad de solicitud.
Esto evita duplicados y conflictos de clave por cambiar de página. Ninguna de estas
lecturas autoriza políticas ni modifica notas. El foco del formulario usa el
desplazamiento mínimo necesario para mostrar el control seleccionado por teclado.
