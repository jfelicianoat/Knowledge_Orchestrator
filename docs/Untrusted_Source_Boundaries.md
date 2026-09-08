# Fuentes no confiables y límites del análisis

El contenido ingerido puede contener instrucciones dirigidas al modelo, nombres de
roles, JSON o etiquetas que simulen instrucciones del sistema. Se conserva como
documento/evidencia; no puede aportar credenciales, permisos, políticas ni aprobación.

Los prompts nuevos de extracción y comparación explicitan ese límite. El JSON de
documentos, identificadores, citas y contexto escapa los signos de etiqueta como
secuencias Unicode. Al decodificarlo se obtiene el texto original, incluidos Unicode
y saltos de línea: no altera las citas ni los índices exigidos por la extracción.
La representación no permite cerrar los bloques del prompt anfitrión con texto de
la fuente. Los embeddings reciben la misma distinción entre datos e instrucciones.

La barrera no depende únicamente del prompt. El Orchestrator valida las respuestas:

- Extracción admite exclusivamente claims con campos conocidos, cita exacta y
  statement coincidente. Un elemento fuera de contrato invalida el lote antes de crear claims.
- Comparación solo admite relación, confianza, impacto, justificación y reemplazo
  conforme al contrato. No admite órdenes, permisos ni aprobación. La sustitución
  debe conservar la evidencia nueva y genera una propuesta revisable.
- Reextraer un claim no elimina su bloqueo guardado aunque el modelo devuelva
  `manual_lock=false`. Publicación revalida los bloqueos independientemente del texto.
- Confianza y rol de fuente proceden de configuración y procedencia registradas;
  valores inventados en el documento o la respuesta no los sustituyen.
- Embeddings solo admiten vectores. No existe un canal de ejecución de herramientas
  en estas respuestas. Las decisiones de publicación requieren revisión o política
  autorizada mediante los servicios de gobernanza.

No se reescriben las peticiones durables que ya estaban guardadas: conservan su
identidad para reintentos/recuperación. Los nuevos prompts se usan al construir
nuevas peticiones. No cambian el contrato público del Broker ni los schemas.

## Evidencia y límites

`tests/test_untrusted_source_boundaries.py`: cinco pruebas pasan en 3,762 s. Usan
una fuente vigilada temporal con instrucciones adversarias, resultados simulados
y comprobación de notas, políticas, control global, reservas, revisiones y confianza.
Se comprueban también etiquetas falsas en identificadores/contexto, Unicode, rechazo
sin claims parciales y conservación de manual_lock.

Esto acredita barreras locales y ausencia de efectos no autorizados en esos casos.
No demuestra que un modelo real nunca siga instrucciones adversarias, ni verifica
la verdad factual de una cita. El ensayo con Broker real y la integración completa
siguen pendientes por la restricción de red documentada.

Batería completa final: **377 pruebas en 176,952 s; 372 pasan y cinco omisiones
Tcl/Tk**. Ruff/mypy pasan sobre 142 archivos y `diff --check` pasa.
