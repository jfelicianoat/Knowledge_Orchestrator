# Product

<!-- impeccable:product-schema 1 -->

## Platform

adaptive

## Users

Una persona técnica usa Knowledge Orchestrator en su equipo Windows para convertir documentos Markdown en conocimiento procesado, revisado y publicado en el vault de Obsidian configurado.

## Product Purpose

La aplicación vigila una carpeta de entrada, valida y organiza documentos, coordina su procesamiento con Broker AI y permite consultar el conocimiento publicado, revisar cambios y resolver incidencias sin depender de una consola.

## Positioning

Une en una sola herramienta de escritorio el ciclo completo del documento, la biblioteca publicada, la política de procesamiento y la revisión semántica, manteniendo el archivo original seguro y trazable.

## Operating Context

- Aplicación Windows instalable y de uso individual.
- Entrada manual mediante importación y entrada automática mediante carpeta vigilada.
- Trabajo habitual con documentos Markdown y un Broker AI disponible en red local.
- La base operativa (SQLite) debe vivir en un disco local; la bóveda puede estar en una carpeta sincronizada.
- Actualización automática de la interfaz a partir del estado durable en SQLite.

## Capabilities and Constraints

- La interfaz es nativa y está construida con Tkinter/ttk.
- La entrada natural es Markdown con el contrato de captura de Knowledge Orchestrator; «Importar documentos» también convierte, previa confirmación, Markdown y texto normales en una captura válida conservando el original.
- El Broker procesa las tareas fuera del hilo de interfaz.
- La interfaz no inventa porcentajes cuando el Broker no informa progreso cuantificable.
- La navegación lateral agrupa trabajo (`Inicio`, `Documentos`, `Revisión`), conocimiento (`Biblioteca`, `Afirmaciones`, `Fuentes`) y sistema (`Actividad`, `Automatización y API`, `Organización`, `Ajustes`), con contadores de lo pendiente.
- La API documental local existe y expone el conocimiento mediante una capa de consulta estable, sin acoplar consumidores externos a widgets, rutas internas o tablas SQLite. Los consumidores se dan de alta y se revocan desde «Automatización y API».
- La recuperación es léxica; los vectores son opcionales, por modelo declarado, y no se generan automáticamente.
- Con «Exigir revisión humana antes de publicar», el resultado queda como borrador y solo se publica tras aprobarlo en la pantalla Documentos.
- Cada afirmación indica si la captura original la respalda (`SOURCE`), si solo la enlazó el modelo (`MODEL_LINKED`) o si solo consta en el resumen (`SUMMARY_ONLY`). Solo las respaldadas proponen cambios en otras notas.

## Brand Commitments

- Nombre del producto: Knowledge Orchestrator.
- Idioma principal: español claro, directo y operativo.
- Los mensajes de error deben explicar el problema, la seguridad del original y la acción de recuperación.

## Evidence on Hand

- Arquitectura, contratos y pruebas existentes en el repositorio.
- Referencia visual aprobada: `C:\Users\jfeli\.codex\generated_images\019fed91-d2a6-71f2-ae4b-43b8b5292e5b\exec-5e5b214c-7fde-4214-975b-0c8715dd3759.png`.
- No hay testimonios, clientes, métricas comerciales ni activos de marca adicionales; no deben inventarse.

## Product Principles

- Hacer visible qué está pasando en menos de cinco segundos.
- Priorizar la recuperación de incidencias sobre la exposición de detalles internos.
- Mantener siempre trazabilidad entre documento, tarea y eventos.
- Ofrecer acciones seguras y reversibles desde el contexto donde se necesitan.
- Conservar la potencia técnica sin exigir que el usuario recuerde el modelo de datos.
- Tratar la biblioteca publicada como la fuente de consulta para personas y, en el futuro, para aplicaciones consumidoras.

## Accessibility & Inclusion

- El estado nunca depende únicamente del color.
- Navegación y acciones principales deben ser utilizables con teclado.
- Texto y controles deben mantener contraste legible en el tema oscuro.
