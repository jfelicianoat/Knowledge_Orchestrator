# Verificación de la auditoría del 27/09/2026

Realizada el 4 de octubre de 2026 contra el commit `846f3c689f5ae5bd1fbbb03386ee6d04f1a7b2bf`.

## Afirmaciones del informe — resultado

| Afirmación del informe | Estado | Nota |
|---|---|---|
| 490 pruebas Python, OK, sin omisiones | ✅ Verificado | `490 passed, 163 subtests passed` (405.82 s) |
| 14 pruebas bridge Node, OK | ✅ Verificado | `bridge.test.cjs`: 0 fallos, 0 cancelados |
| Ruff correcto | ⚠️ Parcial | Pasa con la config del proyecto (`select = E,F,I,UP,B`), pero hay 27 advertencias C901 (complejidad) que el cfg ignora |
| mypy 151 archivos, correcto | ✅ Verificado | `Success: no issues found in 151 source files` |
| 11 escenas de sondas en `probe-results.json` | ❌ No verificable | El archivo no existe en la carpeta de auditoría |

## Hallazgos P1 — verificación contra código actual

Todos los hallazgos P1 del informe son correctos y reproducibles por línea de código:

- **H01** (`publication.py:90`): `publish_ready()` publica sin consultar `human_review_required` — confirmado.
- **H02** (`control.py:17`): `request_cancel` solo modifica la tarea seleccionada — confirmado.
- **H03** (`runtime.py:127-128`): `recover_once()` programa extracción para todas las `PUBLISHED` sin aislamiento por nota — confirmado.
- **H04** (`analisis.py:139`): `volatility: []` produce `TypeError` por pertenencia a conjunto — confirmado.
- **H05** (`trabajos.py:40`): `ON CONFLICT(job_id) DO NOTHING` bloquea reintento con cambio de modelo — confirmado.
- **H06** (`workflow_planner.py:189`): la síntesis concatena todos los partials sin control de ventana — confirmado; las 30 671 tokens son estimaciones del programa, no tokenizador real.
- **H07** (`analisis.py:136`): la evidencia se valida contra la nota generada, no contra la fuente original — confirmado.
- **H08** (`prompting.py:121`): `max_cost_usd` se aplica por tarea, no por documento — confirmado.
- **H09** (`config.py:15`): valor por defecto `Y:/Mi unidad/Vaults/Conocimiento_Youtube` — confirmado.

## Cosas que el informe dejó fuera o deberían refinarse

1. **`probe-results.json`** no existe — las 11 sondas no se pueden inspeccionar; el informe las cita como evidencia adyacente.
2. **H11** (fallback `auto` inalcanzable): el informe cita `estado.py:344` y `workflow_planner.py:215`, pero no explica que la condición de fallback solo contempla `mixture_of_agents`, no `auto`. El código lo confirma, pero la referencia debería ser explícita.
3. **Ruff**: el informe dice "Correcto". Con la config actual pasa, pero las 27 advertencias C901 existen y deberían mencionarse para transparencia.
4. **H13** (`os.replace` entre volúmenes): el informe lo cita bien, pero no recalca que `publication.py:263` usa `os.replace` para mover la nota rechazada entre unidades — mismo riesgo que admite.
5. **Primera ejecución (H09)**: el informe lo clasifica como "código", no como reproducción. No se ensayó en Windows limpio.

## Valoración

El informe es exacto en lo sustancial. Sin las sondas (`probe-results.json`) no todas las afirmaciones son verificables de forma independiente, pero los 9 P1 se confirman por lectura de código.
