# Prueba de integración en Obsidian: preparación y acceso pendiente

9 de septiembre de 2026. **Preparación verificada; prueba real no ejecutada.**

## Estado observado

- El ejecutable instalado de Obsidian declara versión de archivo/producto **1.12.7**.
  Es metadata del ejecutable, no una comprobación de la aplicación funcionando.
- Se encontró e inicializó el control nativo `node_repl` + `@oai/sky` de la habilidad
  Computer Use. Su inventario respondió; no mostró una ventana de Obsidian abierta.
- La llamada a abrir el ejecutable instalado fue rechazada con el mensaje exacto:
  **`Computer Use was not approved to use Obsidian`**. No se indicó otro motivo.
  No se reintentó la apertura por CLI, otra herramienta ni otro ejecutable.
- El usuario autorizó expresamente Computer Use con Obsidian y con la bóveda de
  ensayo. Se reintentó la apertura después de esa autorización; la herramienta
  devolvió de nuevo `Computer Use was not approved to use Obsidian`.
  La autorización humana ya existe; queda pendiente habilitar el acceso efectivo
  en la herramienta. No se ha pedido repetir la autorización ni usado otra vía de apertura.
- La consulta de permisos al gestor de plugins de ChatGPT respondió `not_installed`
  para `Computer Use`. Ese gestor no ha proporcionado un ajuste del control nativo
  de Codex, cuyo inventario sí respondió antes. No se interpreta como ausencia del
  paquete local ni se cambian permisos globales para resolver un acceso específico.

La [documentación oficial de la CLI](https://obsidian.md/help/cli) describe herramientas
para desarrollo de plugins y capturas, pero no se han ejecutado para sortear el rechazo.

## Bóveda preparada

`tools/prepare_obsidian_trial.py` crea una carpeta temporal exclusiva, copia los cinco
archivos del paquete y verifica su igualdad byte a byte. Prepara cinco notas ficticias,
sus hashes base, un manifiesto marcado `PREPARED_NOT_EXECUTED` y una guía. El puente
está desactivado y sin credenciales; todos los casos están marcados `NOT_RUN`.

La bóveda preparada en esta ejecución está en:

`C:\Users\jfeli\AppData\Local\Temp\ko-obsidian-trial-0o2oekhw`

Identidad de ensayo: `e595473d7cd44f3eacba5248211d3e2c`.
Es temporal: comprobar existencia e identidad antes de reutilizarla. Si se limpia
la carpeta temporal, volver a ejecutar el preparador crea un ensayo nuevo, sin
sobrescribir ninguna bóveda. El primer intento bajo `.local` recibió WinError 5 al
crear la carpeta; se utiliza ahora el directorio temporal autorizado. No se cambiaron ACL.

## Evidencia que falta recoger

| Escenario | Evidencia requerida | Estado |
|---|---|---|
| Aplicación | Nota visible en Obsidian, recibo ligado a intención y hash final correcto | No ejecutado |
| Edición concurrente | Edición dentro de una nota abierta en Obsidian después de calcular el cambio; edición conservada y conflicto | No ejecutado |
| Repetición de recibo | Misma petición después de otra edición; no reescritura ni aceptación de un recibo obsoleto como estado actual | No ejecutado |
| Reinicio | Interrupción después de escribir, recuperación con el mismo ID y sin duplicación | No ejecutado |
| Reversión | Confirmación de la revisión anterior, conservación de versiones y comprobación visual de la nota | No ejecutado |

El preparador no contiene un runner ni simula un resultado satisfactorio. Los escenarios
de mantenimiento/reversión requieren el Orchestrator de ensayo, su intención durable
y el puente activo en esta misma bóveda. El recorrido real con Broker, la resistencia
del modelo a contenido adversario y el checkpoint visual integral siguen pendientes
por separado. No sustituirlos por los hashes del paquete ni por las pruebas con mocks.

## Verificación de esta preparación

- Preparador ejecutado: carpeta y manifiesto creados; paquete y cinco bases comprobados.
- Ruff del preparador pasa; diff sin errores de whitespace.
- Sin cambios en código de producción, esquema SQLite, credenciales o bóvedas habituales.
- No se ha repetido la batería de producción: esta preparación no cambia el resultado
  anterior de 440 casos generales ni los 40 casos focalizados posteriores.

El siguiente paso depende del acceso a Obsidian. No se marca el objetivo completo.

## Copia local facilitada por el usuario

El 9 de septiembre el usuario colocó una copia accesible en
`D:\Desarrollo\Proyectos TFM\Obsidian_prueba\Conocimiento_Youtube`.
La lectura de esa copia funciona. No implica acceso a la bóveda de `Y:` ni elimina
el rechazo previo de Computer Use para controlar Obsidian.

Resultados de la revisión de archivos y preparación:

- 134 archivos Markdown existentes, de los cuales 10 son notas visibles; el resto
  está bajo carpetas internas. Ocho de las diez notas visibles fallan la decodificación
  UTF-8 estricta. Las ocho admiten decodificación Windows-1252, lo que no certifica
  por sí solo cuál era su codificación original. No se convirtieron ni sobrescribieron.
- SQLite se abrió exclusivamente en modo de lectura. `PRAGMA quick_check` devuelve
  `ok`; contiene 11 migraciones registradas, cero notas y cero revisiones de notas.
  La presencia de documentos en disco no acredita sincronización con el modelo.
- Se copiaron los cinco archivos del puente a
  `.obsidian/plugins/knowledge-orchestrator-bridge/`, comprobando igualdad byte a byte
  con el paquete del proyecto. `data.json` deja recepción desactivada y nombre de
  secreto vacío. No se activaron complementos ni configuraron credenciales.
- Se crearon cinco notas ficticias en `Pruebas del puente`; se comprobaron sus hashes.
  Los cinco escenarios siguen en `NOT_RUN` y el ensayo en `PREPARED_NOT_EXECUTED`.
- Se verificó por SHA-256 que los 140 archivos anteriores examinados (134 Markdown,
  cinco ajustes JSON y la base de datos) permanecieron idénticos durante la preparación.
- No se inició el runtime sobre la base copiada, no se migró y no se probaron llamadas
  al Broker. El secreto `chatgpt` continúa sin confirmar: copiar el directorio no
  acredita la disponibilidad del almacén de secretos de la aplicación en otra ruta.

Identidad de esta preparación: `71a94a86ba5a418284e1af3a9d8c47d1`.
Informe verificable: `D:\Desarrollo\Proyectos TFM\Obsidian_prueba\preparacion-ensayo.json`.
Guía: `D:\Desarrollo\Proyectos TFM\Obsidian_prueba\LEEME-ensayo.md`.

Esta copia es distinta de la bóveda temporal ficticia descrita antes. Para el recorrido
integrado falta abrir esta copia en Obsidian, configurar el puente y preparar un estado
de ensayo que registre sus documentos sin apuntar a la bóveda original. La codificación
de las notas existentes requiere revisión antes de actualizarlas; los cinco documentos
ficticios nuevos sí se escribieron en UTF-8. Las puertas de aceptación reales siguen abiertas.

## Corrección de instrucciones del puente (10 de septiembre)

El usuario informó que la guía no coincidía con los ajustes del puente. Se revisó
`main.js` y se corrigieron la guía de ensayo y el README con las tres etiquetas exactas
del complemento y la separación entre sus ajustes y el panel del programa Orchestrator.
No se atribuye el problema a una versión diferente sin evidencia visual.

La documentación oficial de SecretComponent coincide con la API usada en el código.
El archivo ejecutable sigue declarando 1.12.7; existe además un paquete de actualización
1.13.7, por lo que la versión del ejecutable no certifica la versión cargada.
El inventario de Computer Use no devolvió ventanas de Obsidian. Una nueva apertura con
el control nativo actualizado volvió a ser rechazada con
`Computer Use was not approved to use Obsidian`, sin motivo adicional. No se empleó
otra vía de apertura. La pantalla concreta del usuario sigue pendiente de observar;
las instrucciones corregidas se identifican como contrastadas con código, no con render.

## Panel real y diagnóstico de credencial (10 de septiembre)

Las tres capturas posteriores del usuario prueban Obsidian **1.13.7**, el puente
instalado/activado, el menú **tres puntos → Ajustes** y el render de sus tres controles.
La recepción aparece encendida, la credencial seleccionada oculta y el puerto 8766.
Esto acredita ese panel concreto, no el recorrido de publicación ni el panel de Tk.

La lectura acotada de `data.json` de la copia confirma `enabled=true`, puerto 8766 y
referencia al nombre `chatgpt`; no se leyó el valor del secreto. `receipts.jsonl` existe
vacío. El Orchestrator aún carece de `obsidian-bridge.json` para esta copia.
Una petición GET sin credencial a `127.0.0.1:8766/v1/status` no llegó a HTTP:
**WinError 10061 / ConnectionRefusedError**. La comprobación del listener no encontró
puerto 8766 en escucha. No se interpreta como 401 ni como token Broker inválido.

El usuario apagó/encendió recepción y confirmó el aviso de una credencial de al menos
32 caracteres. La guarda de `restart()` lo emite cuando `getSecret()` devuelve un valor
ausente o corto, antes de iniciar el servidor. No se puede distinguir ambas causas
solo por ese aviso. Falta configurar el valor de un secreto exclusivo para el puente.

Se preparó un runtime independiente en
`D:\Desarrollo\Proyectos TFM\Obsidian_prueba\Orchestrator_ensayo`, ligado a la copia local.
Construcción sin iniciar workers: SQLite quick_check `ok`, 21 migraciones y cero notas.
No se migró la base copiada de 11 migraciones ni se guardaron credenciales.
`Abrir Orchestrator de ensayo.cmd` fija raíz, inbox y bóveda para ese proceso; la
interfaz aún no se ejecutó. El bloqueo histórico de Tk no se considera resuelto.

## Diagnóstico permanente disponible para recargar (11 de septiembre)

La nueva comprobación mantuvo WinError 10061 y ausencia de configuración del cliente.
Se implementó y copió el puente 0.1.1 al ensayo: **Estado del puente** y **Reintentar
conexión**. Detalle técnico/pruebas en incremento 19 de fase 14. Los cinco archivos
del paquete se verificaron contra el proyecto; ajustes y recibos permanecieron iguales.
No se recargó automáticamente Obsidian ni se probó autenticación con una clave real.
El informe `Obsidian_prueba/actualizacion-puente-0.1.1.json` registra los hashes nuevos,
la copia previa de los dos archivos sustituidos y `USER_RELOAD_REQUIRED`.

La selección de nombre sigue sin acreditar el valor. La nueva fila evita confundir
interruptor activado con servicio disponible. Los cinco escenarios integrados siguen
sin ejecutar; las pruebas Node del arranque no sustituyen una sesión real del plugin.

## Puertos separados para nuevas instalaciones (11 de septiembre)

El incremento 21 corrige la colisión de defaults: API mantiene 8766 y puentes nuevos
usan 8767. La copia existente conserva `data.json`, sus recibos y el puerto 8766.
Solo se sustituyeron los archivos de código/manifest, tras contrastar sus hashes con
la versión preparada antes. El informe `actualizacion-puente-0.1.2.json` conserva los
hashes nuevos y la ruta del paquete anterior. Requiere recarga del complemento.

La lectura real desde `ObsidianConnection.configured_url()` sigue sugiriendo para
este ensayo `http://127.0.0.1:8766`. No se guardó una credencial ni se inició un listener.
En ese caso Servicios propone 8767 para la API, sin iniciarla ni cambiar el puerto de
Obsidian. Se reescribió la guía alrededor de los pasos observados y la configuración
actual, evitando instrucciones mezcladas de versiones anteriores. La nueva sugerencia
de Tk y la conexión autenticada real todavía no están verificadas visualmente.

Comprobación al retomar el 11 de septiembre: paquete preparado 0.1.2, permiso activado,
referencia a secreto configurada y puerto 8766. La consulta sin credencial a
`/v1/status` sigue devolviendo `ConnectError`; no existe aún el archivo protegido de
conexión del Orchestrator de ensayo. Estos datos no prueban que Obsidian haya cargado
el paquete nuevo ni que el valor del secreto sea válido. Se solicitó el texto visible
de **Estado del puente** tras recargar el complemento, sin pedir la clave.

El usuario confirmó recarga; la consulta posterior mantuvo `ConnectError`. Sus nuevas
capturas muestran Obsidian 1.13.7 y Knowledge Orchestrator Bridge **0.1.2** instalado
y activado, junto con una búsqueda vacía en el catálogo. Acreditan la versión visible,
pero todavía no la fila **Estado del puente**. Se indicó abrir **⋮ → Ajustes** junto
al interruptor del complemento en la lista de instalados.

La captura siguiente acredita finalmente la fila **Estado del puente** de 0.1.2:
«Falta una clave válida: el VALOR del secreto debe tener al menos 32 caracteres,
en una sola línea. El nombre es solo una etiqueta». El permiso sigue activado y el
puerto es 8766. La causa observada es la validación del valor del secreto seleccionado
(ausente, corto o con salto de línea); no se inspeccionó ni solicitó su contenido.
El próximo paso es corregir ese valor en **Llavero**, comprobar la selección en
**Credencial compartida** y pulsar **Reintentar conexión**.

Una nueva captura muestra **Escuchando en http://127.0.0.1:8766**. La consulta local
sin credencial obtiene **HTTP 401**: el listener está accesible y exige autenticación.
El archivo de conexión del Orchestrator de ensayo aún no existe. El usuario informa
que el acceso no abre ventana ni muestra error. Se corrigió el arranque Tcl verificado
en Python 3.14.0 y el acceso ahora recoge la salida en `arranque-orchestrator.log`.
Los intentos de apertura automática devolvieron procesos iniciados, pero no una
ventana visible en el inventario de Computer Use. No equivalen a un arranque visual
confirmado. El intento de cerrar el primer proceso iniciado fue denegado por el sistema;
no se volvieron a iniciar instancias tras el segundo intento. Evitar nuevos intentos
automáticos hasta que se confirme el estado de esos procesos.
