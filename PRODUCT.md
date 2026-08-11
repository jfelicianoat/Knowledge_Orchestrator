# Product

<!-- impeccable:product-schema 1 -->

## Platform

adaptive

## Users

Una única persona técnica usa Knowledge Orchestrator en su propio equipo Windows para convertir documentos Markdown en conocimiento procesado y publicado mediante Broker AI.

## Product Purpose

La aplicación vigila una carpeta de entrada, valida y organiza documentos, coordina su procesamiento con Broker AI y permite revisar el estado y resolver incidencias sin depender de una consola.

## Positioning

Une en una sola herramienta de escritorio el seguimiento del ciclo completo del documento, la política de procesamiento y la revisión semántica, manteniendo el archivo original seguro y trazable.

## Operating Context

- Aplicación Windows instalable y de uso individual.
- Entrada manual mediante importación y entrada automática mediante carpeta vigilada.
- Trabajo habitual con documentos Markdown y un Broker AI disponible en red local.
- Actualización automática de la interfaz a partir del estado durable en SQLite.

## Capabilities and Constraints

- La interfaz es nativa y está construida con Tkinter/ttk.
- El formato de entrada admitido actualmente es Markdown con el contrato de captura de Knowledge Orchestrator.
- El Broker procesa las tareas fuera del hilo de interfaz.
- La interfaz no inventa porcentajes cuando el Broker no informa progreso cuantificable.
- Deben conservarse Revisión, Temas y Configuración, además de mejorar Inicio y Trabajo.

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

## Accessibility & Inclusion

- El estado nunca depende únicamente del color.
- Navegación y acciones principales deben ser utilizables con teclado.
- Texto y controles deben mantener contraste legible en el tema oscuro.
