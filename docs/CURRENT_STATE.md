# Estado vigente de Knowledge Orchestrator

Revisión contra el código: **23 de agosto de 2026**.

Este documento prevalece para cuestiones de estado y compatibilidad. `README.md` explica
el uso; `System_Architecture.md` y `Data_Contracts.md` contienen el diseño; los documentos
`Phase_*` son registros históricos de cada entrega.

## Responsabilidad

Knowledge Orchestrator convierte capturas y documentos locales en conocimiento publicado
y revisable. Posee la validación de entrada, clasificación, perfiles, prompts, chunking,
workflow, claims, comparación semántica, revisión humana y proyección a Obsidian. AI Broker
solo ejecuta las tareas técnicas que recibe; no conoce el vault ni la semántica del
workflow.

## Flujo durable

```text
inbox -> estabilidad -> validación v1 -> staging + SHA-256 + SQLite
      -> processing -> clasificación -> workflow -> tareas AI Broker
      -> validación de resultados -> publicación atómica -> completed
                                      └-> claims y candidatos de revisión
```

No existe una transacción distribuida entre NTFS, SQLite, Broker y Obsidian. La consistencia
se obtiene con intenciones durables, claves idempotentes, temporales sincronizados,
reemplazos atómicos y reconciliación al arrancar.

## Capas actuales

- `domain`: contratos, estados y errores tipados.
- `repositories`: SQLite, migraciones y transiciones.
- `services`: ingesta, planificación, publicación, semántica y operaciones.
- `integrations`: cliente HTTP de AI Broker.
- `worker`: watcher, dispatcher, poller y trabajo fuera del hilo UI.
- `ui`: Tkinter/ttk, snapshots de solo lectura y puente de eventos al hilo principal.

## Compatibilidad Broker

El validador de dominio acepta las extensiones aditivas del contrato 2.9 y conserva
compatibilidad con respuestas 2.8. Hay una deuda conocida: el diagnóstico de
`worker/broker_worker.py` todavía compara la capacidad anunciada con `2.8` y puede mostrar
un aviso ante un Broker 2.9 aunque el contrato tipado lo acepte. El aviso no debe
interpretarse como rechazo del payload; debe corregirse en código y cubrirse con una prueba
contractual antes de retirar esta nota.

La autenticación no se presupone ni se descarta: `KO_BROKER_ADMIN_TOKEN` configura
`X-Admin-Token`. Sin token, el cliente omite la cabecera y solo funcionará si el despliegue
acepta ese acceso. Un 401/403 se trata como credencial rotada y recuperable.

## Capacidades implementadas

- watcher `watchdog` con rescan, estabilidad, cancelación y cuarentena;
- ingesta v1, deduplicación, recuperación y fuentes genéricas controladas;
- temas, perfiles versionados, prompts, chunking y síntesis;
- tareas Broker durables, polling, cancelación, modelos y estrategias configurables;
- publicación Obsidian con intención, hash y revisiones;
- extracción de claims, FTS5, embeddings opcionales, comparación, diff y aprobación;
- UI de Resumen, Documentos, Biblioteca, Revisión, Organización y Ajustes;
- backup SQLite, diagnóstico saneado y empaquetado Windows.

## Límites y evidencia pendiente

- No hay RSS, rastreo autónomo de documentación ni búsqueda web autónoma.
- Ningún claim sustituye una nota sin revisión humana; `manual_lock` lo impide siempre.
- Los embeddings son opcionales y no sustituyen la coincidencia exacta de spans.
- La prueba integral real Plugin -> Orchestrator -> Broker -> Obsidian debe ejecutarse y
  archivarse como evidencia de release; las pruebas unitarias y de integración parcial no
  demuestran por sí solas el entorno completo.

## Verificación

```powershell
$env:PYTHONPATH = "src"
python -B -m unittest discover -s tests -v
python -m ruff check src tests
python -m mypy src
```
