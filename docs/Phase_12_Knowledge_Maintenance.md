# Fase 12 — Knowledge maintenance

Checkpoint local de núcleo/API: **5 de septiembre de 2026**. El registro inicial y su
primer incremento se conservan debajo; el cierre vigente está en los diez puntos finales.

Estado inicial: extracción y matching, relaciones semánticas, diff, revisión individual,
snapshot de nota y recuperación existen. La fase 11 ya aporta procedencia durable.
La comparación aún admite texto propuesto no verificable por cita exacta; la aprobación
no fija la revisión de la evidencia nueva y puede afectar claims con spans solapados.
El reindexado desplaza offsets, pero no representa todavía el claim sucesor en la nota
actualizada. Los detalles de impacto/riesgos y edición auditable siguen incompletos.

Plan secuencial:

1. Endurecer evidencia de extracción y parches; fijar hash de ambas notas y comprobar
   otra vez antes de materializar. Impedir daño colateral a claims solapados.
2. Añadir evaluación durable/versionada de propuestas: antes/propuesto, ambas evidencias,
   procedencia/trust, entidades, impacto, justificación resumida, riesgos y elegibilidad.
   La confianza de fuente/modelo no constituye prueba factual ni autorización.
3. Gestionar contradicciones con revisión humana explícita, conservar estados/histórico
   y ampliar edición/rechazo/aprobación con auditoría y revisión optimista.
4. Registrar la presencia del sucesor en notas actualizadas y verificar reindexado.
   Preferir secciones actual/histórico solo con estructura controlada y transformación
   segura; conservar snapshots de revisión en el resto de notas.
5. Ampliar API/detalles de revisión e integrar procedencia desde fuentes monitorizadas.
6. Cubrir escenarios positivos y negativos; ejecutar unittest, ruff y mypy, actualizar
   este registro con el checkpoint. El objetivo completo y las fases 13–14 siguen pendientes.

Archivos previstos: servicio semantic_maintenance y contratos/prompts, repositorio
semántico/conocimiento, migración aditiva si se necesitan evaluaciones/proyecciones,
API de revisión, tests/test_phase_twelve_knowledge_maintenance.py y documentación.

En este punto inicial no había checkpoint. Las verificaciones externas de red/Tk
documentadas en fase 11 siguen pendientes al cierre local de esta fase.

## Primer incremento implementado

- Extracción exige que statement conserve la cita literal. Una cita válida ya no
  permite asociar una afirmación distinta sin respaldo.
- Reemplazos del modelo conservan la cita nueva, sin texto factual inferido añadido.
- El patch guarda source_note_id, source_hash y source_quote. La aprobación valida la
  evidencia al comenzar y tras persistir la intención; la recuperación anterior al
  reemplazo también la revalida. Si cambia, queda CONFLICT y no toca la nota objetivo.
- Se comprueba otra vez el hash objetivo después de escribir el temporal, justo antes
  de reemplazarlo. Sigue existiendo la pequeña ventana filesystem entre check y replace;
  no se afirma disponer de CAS distribuido con editores externos.
- Los parches no pueden afectar otro claim activo solapado. Requieren una propuesta
  conjunta; los no solapados conservan su estado y desplazamiento de offsets existente.
- Los diffs antiguos sin evidencia versionada no se aprueban por esta nueva ruta.
  Falta proporcionar regeneración/edición auditable en el siguiente incremento.
  Las intenciones antiguas ya aprobadas conservan recuperación compatible.

Verificación del incremento: seis tests nuevos pasan; los 36 tests relacionados de
fases 6/9/10 pasan. Batería completa: **216 tests, 215 pasan y 1 omisión explícita de
Tcl/Tk**, 31,387 s. Ruff y mypy pasan (103 archivos). No hay nueva migración aún.
En aquel incremento quedaban pendientes los puntos 2–6, resueltos localmente a continuación.

## Cierre del checkpoint

1. **Estado encontrado.** El flujo tenía extracción/matching/comparación, diff y aplicación
   recuperable. Faltaban evaluación versionada, edición optimista y representación del
   sucesor en la nota destino; la evidencia podía cambiar entre comparación y aplicación.
2. **Diseño propuesto.** Reutilizar servicios y transacciones existentes, añadir una
   evaluación inmutable por revisión y un claim proyectado que conserve el origen.
   Separar la decisión sobre una propuesta de la revisión de vigencia. Mantener Tkinter.
3. **Cambios realizados.** Evaluaciones con impacto/riesgos/evidencias/trust y auditoría
   de tareas/modelos; revisión individual editable desde UI/API; contradicciones
   explícitas; histórico estructurado cuando es seguro y snapshot en otros casos;
   sucesor/reindexado en destino; hashes de ambas notas; reserva de toda la cadena de
   evidencia ante aplicaciones/revisiones concurrentes; reconciliación de derivados.
4. **Archivos modificados.** `services/semantic_maintenance`, `maintenance_assessment.py`,
   `maintenance_layout.py`, `provenance.py`, `knowledge.py`; repositorios semánticos,
   `knowledge_repository.py`, `maintenance_projection.py`, `maintenance_states.py`;
   modelos, contratos/rutas/schemas API, `ui/dashboard/revision.py` y snapshots.
   Documentación de uso en `Maintenance_Review.md` y `Knowledge_API.md`.
5. **Migraciones.** 015 añade `derived_from_claim_id`, hash de evidencia, revisión/actor/
   sucesor de propuesta y `maintenance_proposal_versions` con triggers de inmutabilidad.
   Aditiva; no recrea tablas ni inventa hashes para datos antiguos. Las propuestas
   antiguas se regeneran mediante edición; las intenciones aprobadas siguen recuperables.
6. **Tests añadidos/modificados.** 21 escenarios propios en
   `tests/test_phase_twelve_knowledge_maintenance.py`: evidencia inventada, hashes,
   edición humana durante escritura, recuperación, solapamientos, FTS/vector/procedencia,
   tres versiones de histórico, claims intactos, CAS/edición, fuentes contradictorias,
   permisos/reintentos API, ancestros obsoletos y concurrentes, bloqueo y trust falsificado.
   Se actualizan contratos de migración y expectativas de sucesores/diff en fases 6/7/9/10.
7. **Resultado de verificaciones.** VERIFICADO: `unittest discover -s tests -q`,
   **231 tests en 50,332 s; 230 pasan y una omisión explícita de Tcl/Tk**.
   `ruff check src tests --no-cache`: pasa. `mypy src --no-incremental`: pasa, 108 archivos.
   Los 21 tests propios pasan en 13,990 s. El ciclo fuente → ingesta → publicación →
   propuesta usa Broker simulado y archivos temporales reales.
8. **Riesgos/deuda.** NO VERIFICADO: pantallas Tk por init.tcl, Broker/red reales por
   WinError 10013. REQUIERE PRUEBA REAL: Plugin → Broker → Obsidian y revisión visual.
   Cita exacta respalda la nota publicada, que puede ser resumen IA; no acredita verdad
   factual contra la fuente primaria. La ventana filesystem entre check/replace no es
   CAS distribuido. Las proyecciones no cuentan como fuentes independientes.
9. **Estado del checkpoint.** Núcleo y API locales superados sin tests conocidos fallando.
   Limitaciones externas explícitas permiten avanzar en la implementación independiente;
   el objetivo global y su checkpoint visual continúan pendientes. No hay autoaprobación.
10. **Próximo paso.** Fase 13: evaluar la UI existente y construir navegación, explorador,
    pipeline, revisión comparativa/masiva e histórico, con evidencia visual y funcional.
