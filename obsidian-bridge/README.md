# Puente de publicación para Obsidian

**Integrado con aprobación, recuperación y reversión; prueba en Obsidian real pendiente.**
El paquete está copiado y desactivado en la copia local de ensayo facilitada por el
usuario. No se ha probado su ejecución dentro de Obsidian; consultar
`docs/Obsidian_Trial_Checkpoint.md` en el proyecto para rutas y evidencia.

Entorno acordado: Obsidian en Windows y bóveda local. Requiere Obsidian 1.11.4 o
posterior para su selector/almacén de credenciales. No migra la interfaz del Orchestrator.

## Responsabilidad

El Orchestrator conserva conocimiento, propuestas, políticas, aprobación, snapshots
e intenciones durables. El puente solo recibe una sustitución autenticada y comprueba
el hash de la base dentro del callback síncrono de `Vault.process()`. Rechaza una
base distinta. No extrae claims, decide confianza, ejecuta prompts ni aprueba propuestas.

El servidor se enlaza exclusivamente a `127.0.0.1`, puerto 8767 para instalaciones
nuevas desde 0.1.2. Conserva el puerto guardado en instalaciones existentes. Requiere
Bearer token y rechaza `Origin`, Host distinto y peticiones ligadas a otra bóveda.
La credencial es exclusiva de este puente y diferente de la del Broker. Se selecciona
mediante SecretStorage de Obsidian; `data.json` conserva su nombre, no el valor.
Esto utiliza el almacenamiento de Obsidian; no promete cifrado adicional propio.

## Contrato

- `GET /v1/status`: autenticado; devuelve `protocol: 1` y `vault_id`.
- `POST /v1/apply`: JSON con exactamente `request_id`, `path`, `base_hash`,
  `result_hash`, `content`. IDs/hashes son SHA-256 hexadecimal minúsculo.
- `X-KO-Vault-ID` liga la petición a la ruta real de la bóveda, normalizada con barras
  y minúsculas. Solo se aceptan rutas Markdown relativas, sin traversal/carpetas ocultas.
- Recibo: `request_id`, `result_hash`, `status: applied|already_applied`.
- Error 409: cambio de base, clave reutilizada con otro contenido, bóveda distinta o
  ejecución ambigua que exige revisión. Fallos de infraestructura son 503 sin detalle privado.

El cliente Python `integrations/obsidian_bridge.py` acepta exclusivamente una dirección
loopback literal, ignora proxies de entorno y no sigue redirecciones. Comprueba la
identidad del recibo y el hash real del archivo después de recibirlo. Un recibo anterior
no afirma que el archivo siga sin editarse.

## Recibos y recuperación

`receipts.jsonl` guarda ID, fingerprint y estado; no incluye cuerpos ni credenciales.
Cada entrada se sincroniza antes de avanzar. `PREPARED` precede al cambio de la nota;
`APPLIED` precede a la respuesta. Repetir un recibo aplicado no vuelve a escribir.

Si falta la confirmación después de un reinicio, solo se reconoce aplicación cuando
el archivo coincide con el resultado previsto. Una base antigua o cualquier otro
contenido exige revisión: podría tratarse de una restauración humana después de una
aplicación cuya confirmación se perdió. No se repite silenciosamente ese cambio.

Una última línea incompleta se descarta conservando las entradas anteriores. Un registro
completo corrupto impide cargar el puente. El límite es 10.000 IDs y 16 MiB al cargar;
no hay poda automática de recibos. Un fallo al escribir/sincronizar exige recargar
el puente antes de aceptar más operaciones.

## Archivos para la integración

El paquete consta de `manifest.json`, `main.js`, `bridge-core.cjs`, `server.cjs` y
`journal.cjs`, juntos en la carpeta del plugin. No necesita compilación ni dependencias
Node instaladas en Obsidian. No distribuir `receipts.jsonl`, credenciales o `data.json`
de otra instalación. La activación viene deshabilitada y requiere configuración expresa.

El runtime usa el puente para actualizaciones y reversiones de notas existentes.
Sin conexión deja la intención `APPLYING` pendiente; no reemplaza archivos directamente.
Al reiniciar con el puente disponible recupera las intenciones y conserva la identidad
de la petición. Un 409 produce conflicto; una respuesta perdida se resuelve comprobando
el archivo y el recibo. La publicación inicial conserva su instalación sin sobrescritura.

## Configuración y prueba en una bóveda local de ensayo

1. Copiar los cinco archivos del paquete a
   `.obsidian/plugins/knowledge-orchestrator-bridge/` de la bóveda de ensayo.
2. Activar el complemento en Obsidian y abrir los ajustes de **Knowledge Orchestrator
   Bridge**. La versión 0.1.1 añade **Estado del puente** y **Reintentar conexión**.
   Las filas de configuración son **Permitir propuestas del Orchestrator**
   (interruptor), **Credencial compartida** (selector de nombre de secreto) y **Puerto
   local** (número). Seleccionar primero una credencial exclusiva de al menos 32
   caracteres, usar un puerto distinto al de la API y después activar la recepción. Los controles
   originales aparecen en las capturas del usuario con Obsidian 1.13.7; el render del
   nuevo indicador de estado sigue pendiente.
3. En Orchestrator, Ajustes → Edición segura en Obsidian, guardar
   la dirección local indicada por el puente y la misma credencial. En instalaciones
   nuevas es `http://127.0.0.1:8767`. La bóveda configurada
   en el Orchestrator debe ser la misma que está abierta en Obsidian.
4. Comprobar la conexión. La comprobación solo consulta protocolo e identidad;
   no aplica propuestas. La clave vacía conserva la guardada.
5. Probar una aprobación, edición simultánea, respuesta perdida, reinicio y reversión
   con documentos de ensayo antes de habilitar su uso con documentos reales.

**Dos ventanas distintas:** `Edición segura en Obsidian` pertenece al programa
Knowledge Orchestrator. No es el nombre de un apartado de Obsidian. En el puente se
configura solo el número de puerto; en el Orchestrator, la dirección HTTP completa.

La API conserva su puerto predeterminado `8766`. Desde 0.1.2, un puente nuevo usa
`8767` para poder convivir con ella. No se reescriben puertos ni conexiones guardadas:
la copia de ensayo del usuario mantiene su puente en `8766`. Cuando el panel de
Servicios detecta ese puerto del puente, sugiere `8767` para la API; la persona puede
cambiarlo antes de arrancar. El arranque programático/CLI de la API mantiene su default.
Si aún no hay conexión del cliente guardada, Ajustes sugiere el puerto del `data.json`
del puente de esa bóveda cuando es válido. Esa lectura no guarda credenciales ni
acredita conexión. La dirección protegida ya guardada tiene prioridad.

El nombre de secreto es una etiqueta. Su **valor** debe contener una clave de al menos
32 caracteres en una sola línea. Si se edita en el Llavero sin cambiar el nombre,
**Reintentar conexión** vuelve a leerla. El estado solo declara **Escuchando** después
del evento del servidor; esto no sustituye la comprobación autenticada desde el cliente.
Los fallos de lectura/inicio se muestran sin incluir el mensaje privado de la excepción.

Al sustituir una versión instalada, conservar `data.json` y `receipts.jsonl`, y recargar
el complemento desde la lista de complementos instalados para cargar el código nuevo.

El Orchestrator guarda dirección, identidad de bóveda y credencial cifrada con DPAPI
en un único JSON sustituido de forma atómica, bajo `state/credentials/obsidian-bridge.json`.
La configuración queda ligada al usuario de Windows y a la bóveda; no reutiliza
variables ni archivos de credenciales del Broker. No cambia las carpetas configuradas.
Sin puente disponible, reiniciar después de abrirlo permite recuperar operaciones
ya autorizadas; no hace falta volver a aprobarlas.

Las nuevas intenciones usan un UUID en el campo durable `temp_path` existente,
que identifica la petición sin crear un temporal de nota. Intenciones anteriores
conservan su ruta guardada; las reversiones usan su identificador durable propio.
No hay migración de SQLite ni fallback de reemplazo directo.

Pruebas de desarrollo: `node --test obsidian-bridge/bridge.test.cjs obsidian-bridge/settings.test.cjs` desde la raíz.
Los tests del callback usan un Vault simulado; el transporte loopback y el journal
usan Node y archivos reales temporales. Los tests de dominio inyectan explícitamente
un editor de ensayo que utiliza el cliente HTTP con transporte simulado. También se
verifican runtime sin configurar, recuperación/reversión e intercambio DPAPI real.
No certifican la ejecución dentro de Obsidian ni el render del panel de Ajustes.
Las pruebas de estado usan el arranque real del plugin con un host Obsidian sustituido
y puertos loopback reales; cubren credenciales inválidas, reintento, puerto ocupado,
errores privados y eventos de servidores anteriores.

Referencias oficiales:
[Vault.process](https://docs.obsidian.md/Plugins/Vault),
[almacenamiento de secretos](https://docs.obsidian.md/plugins/guides/secret-storage),
[versiones de la API](https://github.com/obsidianmd/obsidian-api/blob/master/obsidian.d.ts).
