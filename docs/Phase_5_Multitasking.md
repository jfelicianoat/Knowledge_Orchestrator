# Fase 5 — Integración opcional con Multitasking_LLM

## Estado

La integración del Orchestrator está implementada sobre el contrato Broker v2.5. Permanece desactivada por defecto y el uso productivo queda condicionado a que AI Broker conecte providers reales y publique un catálogo de modelos operativo. Las pruebas actuales usan el provider bootstrap determinista del Broker.

## Política por perfil

Cada perfil conserva una política versionada:

- `execution_strategy`: `single`, `mixture_of_agents` o `auto`;
- `multitasking_steps`: subconjunto de `single` y `synthesis`;
- `consensus_preset`: únicamente `fast` en esta fase;
- `consensus_max_proposers`: entre 2 y 5;
- timeout y autorización explícita de fallback a `single`;
- clasificación de datos, cloud, proveedores, coste máximo y revisión humana.

El valor predeterminado es `single`. Activar `mixture_of_agents` o `auto` no afecta automáticamente a todo el workflow: solo los pasos incluidos expresamente en `multitasking_steps` lo solicitan.

`auto` delega la decisión de estrategia en el meta-router del Broker (contrato v2.5): por tarea, el Broker resuelve a `single`, `mixture_of_agents` o `agent`, y la respuesta conserva `auto` en `execution_strategy` durante toda la vida de la tarea (la resolución interna viaja en el evento `strategy.routed` del Broker, no en el contrato). En los pasos elegibles se envía el presupuesto de proponentes y el timeout de consenso por si el meta-router resuelve a mixture. La estrategia `agent` no se expone como valor de perfil a propósito: sus skills (búsqueda web, ejecución de código…) no aplican al flujo de conocimiento, y `auto` ya puede elegirla si conviene.

El contrato v2.5 acepta también el preset `mixture_of_agents/slow`, que autoriza al Broker a ejecutar proponentes en paralelo o por oleadas dentro de una sola tarea; los perfiles siguen fijando `consensus_preset: fast` en esta fase, y el Orchestrator no calcula VRAM ni coordina oleadas.

La migración `008_auto_strategy.sql` amplía el `CHECK` de `execution_strategy` en la tabla `profiles` para admitir `auto`. Como SQLite no permite alterar un `CHECK` de columna, la migración rota la columna (añadir con el `CHECK` nuevo, copiar, eliminar la antigua y renombrar), lo que preserva intactas las claves foráneas hacia `profiles`.

## Límites obligatorios

- Los chunks y embeddings siempre permanecen en `single`.
- En un workflow dividido, el consenso puede aplicarse a la síntesis final.
- El Orchestrator no calcula VRAM, no elige oleadas y no coordina proponentes.
- `local_only` exige cloud desactivado y únicamente proveedor `ollama`.
- Presupuesto, privacidad o validación contractual nunca se degradan para obtener respuesta.
- Consenso y confianza son metadata técnica, no evidencia factual.

## Fallback

El fallback `single` es explícito por perfil y crea otra tarea durable con nuevos `task_id` e `idempotency_key`, enlazada mediante `replacement_for_task_id`. Nunca modifica y reenvía la tarea original con la misma clave. Cubre tanto las tareas `mixture_of_agents` como las `auto` que fallan por quorum o capacidad: el meta-router del Broker pudo resolver `auto` a mixture y fallar por lo mismo.

Solo se permite para fallos de capacidad o consenso:

- `CONSENSUS_QUORUM_NOT_REACHED`;
- `CONSENSUS_PRESET_NOT_IMPLEMENTED`;
- `VRAM_INSUFFICIENT`;
- `MODEL_UNAVAILABLE`;
- `PROVIDER_UNAVAILABLE`.

Errores de presupuesto, privacidad, contrato o contenido terminan el workflow. El arranque reconstruye un fallback que quedara pendiente entre la persistencia del error y su creación.

## Persistencia y progreso

SQLite conserva estrategia, preset, selección, progreso, consenso, scheduling, uso, modelos, warnings y relación de reemplazo. Las fases internas del Broker se muestran como `PROCESSING` sin perder el detalle JSON necesario para la futura cola visual; el estado `waiting_for_tools` (bucle `agent` del Broker esperando tool-calls del cliente) también se mapea a `PROCESSING`, pues no es terminal.

## Exclusión mutua en AI Broker

El dispatcher automático y el endpoint manual usan la misma reclamación `claim_next_queued_task_id`. La operación comprueba que no existe workflow activo, selecciona la siguiente tarea y cambia `queued → routing` dentro de un único `BEGIN IMMEDIATE`. No pueden activar dos workflows simultáneos.

## Verificación

La suite cubre política por perfil, privacidad, chunks `single`, síntesis con consenso, validación de quorum/metadata, fallback único, recuperación tras reinicio y prohibición de degradar un error de presupuesto. La integración directa con la aplicación FastAPI real completa `mixture_of_agents/fast`, persiste consenso y scheduling, y publica la nota final. El resultado sigue procediendo del provider bootstrap hasta conectar Ollama/DeepSeek reales.
