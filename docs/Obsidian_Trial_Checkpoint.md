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
