# Puente de publicación para Obsidian

**En desarrollo: todavía no conectado al flujo de mantenimiento del Orchestrator.**
No está instalado ni activado en ninguna bóveda del usuario.

Entorno acordado: Obsidian en Windows y bóveda local. Requiere Obsidian 1.11.4 o
posterior para su selector/almacén de credenciales. No migra la interfaz del Orchestrator.

## Responsabilidad

El Orchestrator conserva conocimiento, propuestas, políticas, aprobación, snapshots
e intenciones durables. El puente solo recibe una sustitución autenticada y comprueba
el hash de la base dentro del callback síncrono de `Vault.process()`. Rechaza una
base distinta. No extrae claims, decide confianza, ejecuta prompts ni aprueba propuestas.

El servidor se enlaza exclusivamente a `127.0.0.1`, puerto 8766 por defecto. Requiere
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

Antes de instalarlo en una bóveda real quedan pendientes:

1. Integrar el cliente con las intenciones de aprobación, recuperación y reversión.
2. Configurar la conexión y credencial protegida desde el Orchestrator.
3. Sustituir la ruta vulnerable de reemplazo directo; no ocultarla como fallback.
4. Probar edición simultánea, respuesta perdida y reinicio en Obsidian real.

Pruebas de desarrollo: `node --test obsidian-bridge/bridge.test.cjs` desde la raíz.
Los tests del callback usan un Vault simulado; el transporte loopback y el journal
usan Node y archivos reales temporales. No certifican la ejecución dentro de Obsidian.

Referencias oficiales:
[Vault.process](https://docs.obsidian.md/Plugins/Vault),
[almacenamiento de secretos](https://docs.obsidian.md/plugins/guides/secret-storage),
[versiones de la API](https://github.com/obsidianmd/obsidian-api/blob/master/obsidian.d.ts).
