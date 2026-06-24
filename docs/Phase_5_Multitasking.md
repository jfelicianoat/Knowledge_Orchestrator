# Fase 5 — Integración opcional con Multitasking_LLM

## Estado

La integración del Orchestrator está implementada sobre el contrato Broker v2. Permanece desactivada por defecto y el uso productivo queda condicionado a que AI Broker conecte providers reales y publique un catálogo de modelos operativo. Las pruebas actuales usan el provider bootstrap determinista del Broker.

## Política por perfil

Cada perfil conserva una política versionada:

- `execution_strategy`: `single` o `mixture_of_agents`;
- `multitasking_steps`: subconjunto de `single` y `synthesis`;
- `consensus_preset`: únicamente `fast` en esta fase;
- `consensus_max_proposers`: entre 2 y 5;
- timeout y autorización explícita de fallback a `single`;
- clasificación de datos, cloud, proveedores, coste máximo y revisión humana.

El valor predeterminado es `single`. Activar `mixture_of_agents` no afecta automáticamente a todo el workflow: solo los pasos incluidos expresamente en `multitasking_steps` lo solicitan.

`mixture_of_agents/slow` es una extensión posterior: permitirá al Broker ejecutar proponentes en paralelo o por oleadas dentro de una sola tarea. No se añade todavía al enum ni a la migración del perfil. El Orchestrator solo lo habilitará después de que el Broker publique `slow` en su negociación de capacidades y complete las pruebas de recursos, cancelación y coste.

## Límites obligatorios

- Los chunks y embeddings siempre permanecen en `single`.
- En un workflow dividido, el consenso puede aplicarse a la síntesis final.
- El Orchestrator no calcula VRAM, no elige oleadas y no coordina proponentes.
- `local_only` exige cloud desactivado y únicamente proveedor `ollama`.
- Presupuesto, privacidad o validación contractual nunca se degradan para obtener respuesta.
- Consenso y confianza son metadata técnica, no evidencia factual.

## Fallback

El fallback `single` es explícito por perfil y crea otra tarea durable con nuevos `task_id` e `idempotency_key`, enlazada mediante `replacement_for_task_id`. Nunca modifica y reenvía la tarea original con la misma clave.

Solo se permite para fallos de capacidad o consenso:

- `CONSENSUS_QUORUM_NOT_REACHED`;
- `CONSENSUS_PRESET_NOT_IMPLEMENTED`;
- `VRAM_INSUFFICIENT`;
- `MODEL_UNAVAILABLE`;
- `PROVIDER_UNAVAILABLE`.

Errores de presupuesto, privacidad, contrato o contenido terminan el workflow. El arranque reconstruye un fallback que quedara pendiente entre la persistencia del error y su creación.

## Persistencia y progreso

SQLite conserva estrategia, preset, selección, progreso, consenso, scheduling, uso, modelos, warnings y relación de reemplazo. Las fases internas del Broker se muestran como `PROCESSING` sin perder el detalle JSON necesario para la futura cola visual.

## Exclusión mutua en AI Broker

El dispatcher automático y el endpoint manual usan la misma reclamación `claim_next_queued_task_id`. La operación comprueba que no existe workflow activo, selecciona la siguiente tarea y cambia `queued → routing` dentro de un único `BEGIN IMMEDIATE`. No pueden activar dos workflows simultáneos.

## Verificación

La suite cubre política por perfil, privacidad, chunks `single`, síntesis con consenso, validación de quorum/metadata, fallback único, recuperación tras reinicio y prohibición de degradar un error de presupuesto. La integración directa con la aplicación FastAPI real completa `mixture_of_agents/fast`, persiste consenso y scheduling, y publica la nota final. El resultado sigue procediendo del provider bootstrap hasta conectar Ollama/DeepSeek reales.
