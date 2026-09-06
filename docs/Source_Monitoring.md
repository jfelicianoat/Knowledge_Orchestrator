# Fuentes vigiladas

La pestaña **Fuentes** configura Web y RSS/Atom, frecuencia, activación, ámbito,
categoría, confianza y política de ingesta. Se mantiene Tkinter/ttk. El ámbito es
una etiqueta de contexto, no un filtro ni una autorización. Categoría y confianza
expresan procedencia; no verifican hechos.

## Uso y API

1. Añadir una URL HTTP(S) pública. Frecuencia entre 60 segundos y 30 días.
2. Mantener **Revisar primero** para inspeccionar las novedades antes de incorporarlas.
3. Seleccionar una novedad y pulsar **Incorporar novedad seleccionada**. Esto entrega
   una captura al flujo documental, que después extrae claims y propone cambios.
4. **Incorporar novedades** automatiza explícitamente esa entrega por fuente. Tampoco
   aprueba propuestas ni modifica el conocimiento por sí misma.
5. **Comprobar ahora** agenda una comprobación fuera del hilo UI. Activar antes las
   fuentes pausadas. Editar invalida descargas que usen la configuración anterior.

No se crean fuentes predeterminadas. El scheduler arranca con el servicio, tanto con
UI como con API/consola, y funciona aunque AI Broker esté desconectado.

La API exige el permiso específico `sources` en `KO_API_CLIENTS`; `read` e `ingest`
no permiten gestionar fuentes ni elevar su confianza. La gestión abarca la bóveda
completa de este runtime. Rutas bajo `/api/v1`:

| Método y ruta | Operación |
|---|---|
| POST `/sources` | Registro idempotente; devuelve fuente y Location |
| GET `/sources` | Configuración y salud, limit/offset |
| GET `/sources/{source_id}` | Detalle |
| PATCH `/sources/{source_id}` | Configuración completa y expected_revision; 409 si cambió |
| POST `/sources/{source_id}/check` | Comprobación en segundo plano; 202 |
| GET `/sources/{source_id}/checks` | Historial, limit/offset |
| GET `/source-changes` | Novedades, filtros source_id/status y limit/offset |
| GET `/source-changes/{change_id}` | Contenido observado, hashes y procedencia |
| POST `/source-changes/{change_id}/ingest` | Incorporación; 202, repetible sin duplicar |

Los POST requieren `Idempotency-Key`. Incorporar una novedad es idempotente por
`change_id` incluso con otra clave; no acepta contenido arbitrario de reemplazo.
Schemas disponibles en `/api/v1/openapi.json`.

Configuración: `name`, `kind` (`web`/`rss`), `location`, `interval_seconds` (3600),
`enabled` (true), `scope` (vacío), `trust_level` (50), `source_role` (`generic`),
`ingestion_policy` (`review`) y `credential_env` (vacío). Categorías admitidas:
`official_documentation`, `official_repository`, `official_blog`, `secondary`, `generic`.
Cada edición conserva una revisión inmutable con actor y fecha en `source_revisions`.

## Credenciales y límites

Para autenticación Bearer, configurar una variable de entorno con prefijo
`KO_SOURCE_SECRET_` y guardar solo su **nombre** en `credential_env`. El token se lee
temporalmente al descargar, exige HTTPS y no se reenvía a otro origen. No introducir
secretos en URL, nombre o ámbito. El token de AI Broker es independiente.

Cada destino y redirección se resuelve y se valida como dirección pública; la conexión
usa esa misma IP y TLS verifica el hostname original. No se permiten redes internas,
loopback, puertos distintos de 80/443, redirecciones HTTPS→HTTP, scripts ni seguimiento
de enlaces de artículos. URLs con credenciales o parámetros habituales de secretos
se rechazan. Los errores persistidos son códigos, sin cuerpos HTTP ni tokens.

Límites: 1 MiB por respuesta, 500.000 caracteres por contenido, 200 entradas por feed,
cuatro comprobaciones simultáneas y tres redirecciones. HTTP solicita identity;
se rechazan compresión, respuestas truncadas y formatos no admitidos. XML rechaza
DTD/entidades y UTF-16/32. Web no renderiza JavaScript.

## Detección, recuperación y procedencia

Web extrae texto visible, omite script/style/navegación y normaliza espacios conservando
indentación en pre; admite también texto plano. RSS/Atom utiliza contenido/summary/
description e identidad id/guid/enlace. Orden, pubDate/updated y cambios de formato
irrelevante no generan novedades. Sin identidad estable se utiliza hash de contenido.
Retirar una entrada del feed no retira claims ni borra observaciones anteriores.

La primera observación es una novedad. A→B→A conserva tres observaciones; A→A no duplica.
ETag/Last-Modified permiten comprobaciones condicionales; 304 conserva la instantánea.
Observaciones, punteros por ítem, hashes y resultado se guardan en una sola transacción.
La procedencia conserva la confianza y configuración originales, aunque después cambien.

Cada comprobación tiene reserva durable de 90 segundos. Al expirar pasa a ABANDONED
y se recupera; se descartan resultados tardíos o de una configuración anterior.
Errores de comprobación y de entrega tienen backoff de 60 segundos hasta una hora.
Las entregas fallidas conservan READY, delivery_error y su siguiente intento.
Una fuente caída o entrega fallida no bloquea las demás comprobaciones.

La ingesta tiene un propietario interno que no puede suplantar un consumidor API y
una clave derivada de change_id. Tras una caída entre recibo y enlace se reutiliza
el mismo recibo. DELIVERED significa **entrega al flujo**, no publicación final.
Para el progreso posterior consultar api_ingestions y el workflow documental.
La API obtiene procedencia enlazando ese recibo durable; no confía en frontmatter
arbitrario para atribuir una captura a una fuente oficial.

## Pendientes y restricciones

GitHub/API/búsquedas programadas requieren nuevos conectores y configuración explícita.
No hay rastreo recursivo, selectores CSS, ejecución JS ni red privada opt-in.
Fuentes que excedan límites necesitan un feed ajustado o un conector específico.

La descarga tiene presupuesto de 25 segundos y operaciones de socket de hasta ocho.
DNS conserva el timeout del SO; un DNS bloqueado puede ocupar uno de los cuatro hilos.
Los hilos son daemon: parar el scheduler deja las comprobaciones en curso terminar
o recuperarse al siguiente arranque. No se cancelan transacciones a la fuerza.

En este entorno la descarga pública devuelve NETWORK_DENIED y Tcl/Tk no inicializa
init.tcl. Pruebas simuladas y bases temporales no acreditan red ni pantalla reales.
