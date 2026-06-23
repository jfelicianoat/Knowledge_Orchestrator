# Estudio de integración de Multitasking_LLM

Fecha: 23 de junio de 2026

**Actualización:** la política Multitasking_LLM del Orchestrator quedó implementada el 23 de junio de 2026 para `mixture_of_agents/fast`, con `single` por defecto, límites por perfil/paso y fallback seguro. La activación productiva aún requiere providers reales, catálogo de modelos y benchmark.

## Conclusión

La opción denominada `Multitasking_LLM` corresponde en el AI Broker actual a `execution.strategy: mixture_of_agents`: una sola tarea del Broker puede ejecutar varios proponentes y un árbitro, con planificación interna `parallel`, `waves` o `sequential`.

La integración es viable sin trasladar lógica de conocimiento al Broker. El Orchestrator seguirá siendo responsable de fuentes, prompts finales, chunking, workflows, validación semántica, publicación y Obsidian. El Broker será responsable de ejecutar la estrategia LLM solicitada, seleccionar modelos dentro de las restricciones, proteger VRAM y devolver un único resultado técnico sintetizado.

No debe activarse por defecto todavía. La base contractual v2 funciona en `single` y consenso; el provider actual del Broker sigue siendo bootstrap.

## Estado real de compatibilidad

| Área | Orchestrator actual | AI Broker actual | Implicación |
|---|---|---|---|
| Petición | Adaptador v2 implementado | `idempotency_key`, `request_id`, `content`, `output`, `generation`, `model_requirements`, `execution`, `risk`, `priority` | Compatible en `single` |
| Identidad | ID local e `idempotency_key` durables | `task_id` propio, clave única y hash canónico | Reenvío seguro; conflicto devuelve `409` |
| Estados | Mapeo durable a estados internos | fases detalladas y terminales `completed`, `failed`, `cancelled` | Compatible y con progreso persistido |
| Resultado | Normaliza a `assistant_content` interno | `result.result_markdown`, uso y modelos | Compatible; metadata técnica conservada |
| Ejecución | Una tarea equivale a una inferencia | Una tarea MoA contiene varias invocaciones internas | Debe cambiar la semántica documentada, no el workflow de negocio |
| Despacho | Servicio siempre encendido | Dispatcher de fondo; `/dispatcher/tick` queda para diagnóstico | Resuelto |
| Modelos | Descubrimiento periódico requerido | `/api/v1/models` devuelve todavía un catálogo vacío | La selección manual/híbrida no puede habilitarse aún |
| Providers | Se esperan LLM reales | El coordinador indica proveedor bootstrap | No es una integración productiva todavía |

## Cambio de modelo mental

Debe mantenerse un solo workflow activo global en el Broker, pero ese workflow puede contener varias invocaciones internas. La decisión de ejecutar en paralelo, por oleadas o secuencialmente pertenece exclusivamente al Broker y a su planificador de recursos.

El Orchestrator puede continuar enviando tareas a la cola sin esperar resultados. No calcula VRAM, no carga modelos y no coordina proponentes. Solo decide si una tarea concreta solicita estrategia `single` o `mixture_of_agents`, junto con límites de privacidad, coste, tiempo y revisión humana.

## Política recomendada en el Orchestrator

`single` debe seguir siendo el valor predeterminado. Multitasking_LLM se habilitará mediante política explícita y versionada por perfil y tipo de paso, nunca porque el contenido del usuario o un LLM lo solicite.

Uso inicial recomendado:

- síntesis final compleja;
- comparación de evidencias contradictorias;
- decisiones de alto impacto que ya requieran revisión humana;
- análisis donde el benchmark interno demuestre mejora frente a `single`.

No usar inicialmente para:

- cada chunk de una transcripción, porque multiplicaría invocaciones, coste y latencia;
- embeddings, clasificación por keywords o validaciones deterministas;
- tareas sencillas de extracción o reformateo;
- sustituir evidencia local por “consenso” de modelos.

En workflows con chunks, los chunks permanecerán normalmente en `single` y solo la síntesis final podrá solicitar consenso. No se permitirán fan-outs anidados sin un límite explícito.

## Contrato previsto

El contrato compartido v2 ya está congelado para `single`. La fase 5 lo reutilizará para `mixture_of_agents`. El adaptador transforma el prompt final ya renderizado en `content.prompt` y añade únicamente metadata allowlist. La petición incluye:

- `request_id`/clave idempotente durable y hash del payload;
- `execution.strategy`: `single` o `mixture_of_agents`;
- preset inicialmente limitado a `fast` mientras el Broker no implemente los demás;
- selección `auto` en el primer incremento; `manual` e `hybrid` solo con catálogo real;
- máximos de proponentes, jueces, rondas, timeout y coste;
- `data_classification`, `cloud_allowed`, proveedores permitidos y revisión humana.

El Broker garantiza que la misma clave y el mismo hash devuelven la tarea existente con `200`, incluso tras reiniciar, y que la misma clave con contenido distinto devuelve `409`.

## Persistencia y estados

El Orchestrator deberá conservar por tarea:

- estrategia, preset y modo de selección solicitados y realmente usados;
- ID asignado por el Broker separado del ID local;
- fase y unidades de progreso;
- consenso, desacuerdos, advertencias, scheduling, coste y modelos usados;
- versión del contrato y del algoritmo de consenso.

Las fases `routing`, `planning`, `resource_planning`, `proposing`, `evaluating`, `debating`, `synthesizing` y `verifying` se mapearán localmente a `PROCESSING`, conservando el detalle para la cola visual. `completed`, `failed` y `cancelled` se mapearán a estados terminales locales.

Un consenso no es evidencia factual. Las propuestas, puntuaciones o confianza del Broker son metadata técnica; la publicación y el mantenimiento semántico seguirán exigiendo fuentes locales y validación del Orchestrator.

## Reglas de implementación por capa

| Capa | Responsabilidad permitida | Prohibido |
|---|---|---|
| Dominio | Política versionada de ejecución, enums, límites y mapeos de estado | HTTP, SQLite, VRAM o selección dinámica de modelos disponibles |
| Servicios | Elegir `single`/consenso según perfil y paso; aplicar privacidad, coste, fallback y revisión | Permitir que el texto de entrada cambie la política o coordinar proponentes |
| Integración Broker | Adaptar y validar contrato, timeouts y errores tipados | Construir prompts de negocio, corregir respuestas inválidas o decidir evidencias |
| Repositorios | Migraciones y persistencia de IDs, estrategia, progreso, resultado y auditoría | Llamadas de red o decisiones de routing |
| Worker | Despacho, polling, cancelación, recuperación y eventos thread-safe | Acceder a widgets o bloquear el watcher de archivos |
| UI futura | Mostrar política, fases, coste, warnings y recoger decisiones explícitas | Acceso directo a HTTP/SQLite o presentar confianza como certeza |

Las dependencias deben seguir fluyendo desde servicios hacia puertos explícitos de repositorio e integración. El contrato Broker se probará con fixtures canónicas compartidas; no se duplicarán esquemas divergentes escritos a mano sin una prueba de compatibilidad.

Antipatrones expresamente prohibidos:

- activar consenso automáticamente para toda tarea;
- lanzar consenso por cada chunk;
- calcular o reservar VRAM en el Orchestrator;
- reenviar tras timeout con un identificador nuevo;
- degradar privacidad, quórum o coste para obtener una respuesta;
- tratar un resultado parcial como consenso completo;
- publicar directamente artefactos internos de proponentes;
- almacenar cadenas privadas de razonamiento o secretos del proveedor.

## Seguridad, coste y UX

- `local_only` debe impedir cualquier proveedor cloud tanto en el contrato como en la respuesta observada.
- El coste máximo es un límite duro, no una preferencia.
- Un fallo de quórum no debe degradarse silenciosamente a `single` salvo política explícita.
- Los timeouts y expectativas de latencia deben ser mayores que en `single`.
- La UI mostrará fase, invocaciones completadas/total, oleadas, coste y desacuerdos; no mostrará porcentajes inventados.
- El contenido de candidatos se tratará como datos no confiables para evitar prompt injection entre modelos.

## Criterios de aceptación de la fase futura

1. Compatibilidad real `single` contra AI Broker sin romper workflows existentes.
2. Reenvío tras caída sin crear una segunda tarea ni repetir coste.
3. `mixture_of_agents/fast` produce un único resultado publicable y conserva metadata de consenso.
4. Los chunks siguen en `single` y la síntesis puede usar consenso por política.
5. `local_only` nunca usa cloud; coste, timeout y quórum se respetan.
6. Todos los estados y errores del Broker se mapean y recuperan tras reinicio.
7. La indisponibilidad o falta de capacidad puede usar `single` solo cuando el perfil lo autorice.
8. Un benchmark representativo demuestra una mejora material antes de habilitar consenso por defecto.

La suite deberá cubrir dominio/políticas, validadores de contrato, migración SQLite, transiciones del worker, recuperación tras caída, errores tipados y la frontera UI mediante eventos. La prueba extremo a extremo incluirá un Broker real en `single` y en `mixture_of_agents/fast`.

## Decisión de planificación

Se inserta una nueva **Fase 5 — Integración opcional con Multitasking_LLM**. El mantenimiento semántico pasa a fase 6, la UI a fase 7 y el empaquetado a fase 8. No se modifica código del Orchestrator en este cambio documental.
