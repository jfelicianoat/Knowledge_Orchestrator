# Coordinación al sustituir notas existentes

Estado: **defecto reproducido; puente Obsidian en desarrollo, aún sin integrar**.
Ensayo del 8 de septiembre de 2026. Este documento no rebaja la exigencia de conservar
ediciones humanas ni autoriza cambios de tecnología o restricciones de uso.

## Invariante y reproducción

La especificación exige que una nota distinta de la base del patch produzca `CONFLICT`
sin sobrescribirla. El `os.replace` de `SemanticMaintenanceService._materialize` deja
una ventana después de calcular el último hash. La reversión reutiliza ese método.

`tools/probe_note_replacement.py` ejecuta el método real sobre un directorio temporal
propio e interpone una escritura de otro proceso inmediatamente antes de `os.replace`.
El escritor terminó correctamente, pero el contenido final fue `proposed`:
`human_edit_preserved=false`. El diagnóstico **contradice el invariante en esa ventana**.
Los tests anteriores de edición antes del chequeo siguen siendo válidos para ese
momento concreto; no acreditan el intervalo posterior.

Ejecución desde el proyecto, con su entorno Python:

```powershell
$env:PYTHONPATH='src'
& .venv/Scripts/python.exe -B tools/probe_note_replacement.py
```

El script no utiliza configuración, SQLite, credenciales, red ni notas del usuario.
Su salida describe comportamiento; finalizar con código cero no certifica seguridad.

## Ensayo de protección nativa

Se abrió el archivo con lectura, sin compartir escritura. Mientras permanecía abierto,
otro proceso intentó escribir y el ensayo intentó reemplazar usando
`SetFileInformationByHandle(FileRenameInfoEx)`. Ambos handles se cerraron antes de
inspeccionar el resultado y retirar el directorio temporal.

| Acceso compartido al destino | Flags de reemplazo | Escritura del otro proceso | Reemplazo propio | Contenido final |
|---|---|---|---|---|
| READ | REPLACE | Rechazada | Rechazado, WinError 5 | base |
| READ | REPLACE + POSIX | Rechazada | Rechazado, WinError 32 | base |
| READ + DELETE | REPLACE | Rechazada | Rechazado, WinError 5 | base |
| READ + DELETE | REPLACE + POSIX | Rechazada | Permitido | proposed |

Conclusión limitada: negar escritura y borrado impide también el reemplazo propio
probado. Compartir DELETE permite la operación POSIX, pero no concede exclusividad
de renombrado a este proceso. No se ha probado que esa combinación cierre la carrera
con otros escritores que sustituyan el archivo. No se adopta como solución.

Un ensayo separado creó una transacción KTM e intentó abrir un archivo temporal con
`CreateFileTransactedW`: recibió **WinError 6832**, objeto no permitido en una transacción.
Se cerró la transacción; no se modificaron permisos ni configuración del sistema.
No se atribuye este resultado a una causa global sin demostrarla. Además, Microsoft
recomienda alternativas a TxF y advierte sobre su disponibilidad futura.

Fuentes primarias de las operaciones y límites:

- [CreateFileW: acceso y compartición](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew).
- [FILE_RENAME_INFORMATION: reemplazo POSIX y handles abiertos](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/ns-ntifs-_file_rename_information).
- [Transactional NTFS y recomendación de alternativas](https://learn.microsoft.com/en-us/windows/win32/fileio/transactional-ntfs-portal).

## Decisión de integración pendiente

El usuario ha confirmado expresamente **Obsidian en Windows y bóveda local**.
La vía elegida es coordinar la escritura mediante un puente a Obsidian. El paquete
se está preparando y verificando; aún no se han sustituido documentos, activado
políticas ni instalado el puente en una bóveda real.

Para el caso Obsidian, su API documenta `Vault.process()` como lectura/modificación
coordinada. Se desarrolla el puente de publicación, conservando en
el Orchestrator propuesta, autorización, hash, snapshot, intención y recibo durable.
El puente no decidiría conocimiento ni políticas. Una prueba debe acreditar edición
concurrente, respuesta perdida, reinicio e idempotencia antes de usarlo en una bóveda.
La documentación de esa API no prueba por sí sola coordinación de escritores externos.
[Fuente: API Vault de Obsidian](https://docs.obsidian.md/Plugins/Vault).

Para otros editores o almacenamiento compartido hay que comprobar qué protocolo común
pueden respetar. Un lock lateral ignorado por el editor, otro chequeo de hash o una
copia de respaldo después de sobrescribir no satisfacen por sí solos el invariante.
No se selecciona silenciosamente un entorno más restringido para cerrar el checkpoint.

## Consecuencias para la aceptación

- El incremento 17 protege instalación de notas **nuevas** y sigue vigente.
- La actualización y reversión de notas **existentes** conservan el defecto reproducido.
- No se han activado políticas, ejecutado cambios reales ni instalado un puente.
- La batería anterior (425 casos, 420 pasan, cinco omisiones Tk) no cubría esta carrera.
- El gate de publicación con editor externo y el criterio global de consistencia quedan
  abiertos por evidencia contradictoria, no solo por falta de una prueba visual.

Implementación inicial del puente y contrato: `../obsidian-bridge/README.md`.
Diez pruebas Node cubren callback, journal y transporte; seis pruebas Python verifican
el cliente y los recibos. La ruta vulnerable sigue vigente hasta completar la integración.
