# Fase 2 — Dominio, temas y perfiles

## Fuentes admitidas

`source_type` sigue siendo extensible, pero toda fuente conserva un origen controlado:

- `PLUGIN_CAPTURE`: captura YouTube con `plugin_version`.
- `USER_FILE`: documento o transcripción depositado explícitamente en el inbox.
- `OBSIDIAN_NOTE`: nota local ya existente en Obsidian.

Se rechazan explícitamente `rss`, búsquedas web autónomas, conectores automáticos a APIs y documentación vigilada. El proyecto no contiene productores, schedulers ni conectores para esas fuentes.

## Clasificación de temas

Los temas activos se evalúan por `position` ascendente. Gana el primero cuya keyword completa aparece en título, canal, `source_type`, tags o keywords de la captura. La normalización ignora mayúsculas y acentos, pero no confunde keywords cortas con partes de otra palabra.

Si no existe coincidencia se asigna el tema reservado `_inbox`. Sus invariantes son:

- carpeta `_inbox`;
- última posición;
- sin keywords;
- sin actualización por caducidad.

Las carpetas son rutas relativas al vault, se validan para Windows y se crean automáticamente. No se permiten `..`, rutas absolutas, caracteres inválidos ni nombres como `CON`, `NUL`, `COM1` o `LPT1`.

## Perfiles

Cada tema referencia un perfil activo. Los perfiles se editan mediante `ProfileService` y usan revisión optimista para impedir sobrescrituras concurrentes.

Campos principales:

- `system_prompt`
- `user_prompt`, que debe contener `{transcript}`
- `chunk_prompt`, que debe contener `{chunk}`
- `synthesis_prompt`, que debe contener `{partial_results}`
- `preferred_model`, `fallback_allowed`, `temperature` y `max_output_tokens`

Solo se aceptan placeholders simples incluidos en la allowlist. No se permite acceso a atributos, índices, conversiones ni formatos de Python.

La migración crea el perfil inicial `Técnico Profundo`. La edición visual llegará en la fase 7; la capa de servicio y persistencia ya está operativa.

## Vigencia

Si el tema permite actualización y define `obsolescence_days`, la fecha se calcula desde `captured_at` y se persiste en la captura. `null` significa que no caduca. Alcanzar la fecha solo marca conocimiento para revisión; no genera una actualización factual ni busca fuentes nuevas.

## Persistencia y recuperación

La migración `002_domain_topics_profiles.sql` amplía bases de fase 1 sin recrearlas. Una captura `PENDING` que todavía no tenga dominio asignado se enriquece al arrancar, por lo que una caída entre ingesta y clasificación no deja el registro permanentemente incompleto.

La lógica reside en `services/`; los repositorios se limitan a SQLite y la UI no accede a ninguno de ellos directamente.
