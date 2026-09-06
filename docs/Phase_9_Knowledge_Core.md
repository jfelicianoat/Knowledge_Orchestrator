# Fase 9 — Knowledge Core

Checkpoint de implementación: 5 de septiembre de 2026.

## 1. Estado encontrado

La fase 6 conservaba evidencia y revisiones de notas, pero solo distinguía ACTIVE,
SUPERSEDED y RETRACTED. La aplicación no enlazaba el claim sustituido con el sucesor.
El diff validaba su fragmento y no detectaba una edición externa fuera de ese fragmento.
La referencia inicial pasó 164 pruebas antes de esta ampliación.

## 2. Diseño propuesto y aplicado

Modelo aditivo. Se conserva `status` para compatibilidad interna y se incorpora
`knowledge_state`: CURRENT, HISTORICAL, SUPERSEDED, DISPUTED, UNCERTAIN, REVIEW_REQUIRED.
CURRENT significa vigente en el modelo local, no verificación factual.
Las fechas describen vigencia operativa conocida, sin inventar fechas del mundo real.
Las entidades se vinculan mediante una relación de varios a varios. La normalización
inicial usa `lower(trim(...))` de SQLite; no fusiona automáticamente alias semánticos.

## 3. Cambios realizados

- Alta de entidades y estado inicial en la transacción del claim y su evidencia.
- Consultas paginadas current/historical/all y por estado, entidad o nota.
- Cadena de sucesión consultable desde predecesores y sucesores.
- Historial de estados inmutable, revisión optimista y decisiones justificadas.
- Transición a SUPERSEDED tras publicación de una relación SUPERSEDES aprobada.
  EXTENDS/CONTRADICTS archivan la formulación anterior como HISTORICAL.
- Recuperación de publicación y registro temporal en la misma transacción SQLite.
- Validación del hash completo antes de aprobar y después de persistir la intención.
- Bloqueos de claims superpuestos y exclusión de aplicaciones concurrentes sobre una nota.
- Reconciliación al arrancar: detecta CONFLICT/MISSING sin modificar archivos humanos
  ni claims bloqueados; las notas observadas en conflicto se excluyen de current.

## 4. Archivos modificados

Nuevos: `domain/knowledge.py`, `repositories/knowledge_repository.py`, `services/knowledge.py`,
`migrations/012_knowledge_core.sql`, `tests/test_phase_nine_knowledge_core.py` y este registro.
Integración: modelo KnowledgeClaim, repositorio semántico (afirmaciones, filas, candidatos,
base y embeddings), servicio SemanticMaintenanceService, runtime y prueba de migraciones.
Los cambios locales anteriores se conservan.

## 5. Migraciones

012 añade columnas, índices, entidades, vínculos, historial y observaciones de reconciliación.
Mantiene IDs, spans, evidencia y filas existentes. Recupera sucesores legacy cuando existe
un candidato APPLIED. Cuando no existe esa evidencia, conserva el histórico sin inventar
un sucesor. No se recrea la base de datos. Solo se ejecutó sobre bases temporales de pruebas.

## 6. Tests añadidos/modificados

Diez pruebas nuevas: sucesión y claim no afectado, idempotencia de reindexado, revisión de
estados, bloqueo después del diff, edición fuera del span, edición durante aprobación,
recuperación sin duplicar histórico, reconciliación sin sobrescritura, inmutabilidad y
migración de base legacy con datos. Se actualiza el número esperado de migraciones a 12.
Se reutiliza la preparación de notas de fase 6; sus once pruebas también pasan.

## 7. Resultado de verificaciones

VERIFICADO con `.venv/Scripts/python.exe` y `PYTHONPATH=src`:

- `python -B -m unittest discover -s tests -q`: **174 pruebas OK**, 28,305 segundos.
- `python -m ruff check src tests --no-cache`: **All checks passed**.
- `python -m mypy src --no-incremental --cache-dir <directorio temporal>`:
  **Success: no issues found in 85 source files**.
- `git diff --check`: sin errores de espacios; avisos normales LF/CRLF de Windows.

El destino inicial de caché `NUL` provocó un error interno de mypy; con un directorio
temporal escribible la comprobación completa pasó. No es un fallo de tipos pendiente.

## 8. Riesgos y deuda

NO VERIFICADO: ejecución sobre los datos reales del usuario y aplicación real con Broker.
REQUIERE PRUEBA REAL: cadena Plugin → Orchestrator → Broker → Obsidian.
La reconciliación representa la última observación, no vigilancia continua; las próximas
fases deben actualizarla antes de servir consultas y durante el mantenimiento.
Una propuesta legacy sin hash de comparación necesita regenerar su diff antes de aprobarse;
se rechaza su aprobación para no atribuirle una base que nunca se registró.
Las revisiones conservan el documento anterior; la reorganización Estado actual/Histórico,
las proyecciones adicionales de claims y la edición de propuestas se completarán en fase 12.
No existe una transacción distribuida con editores externos: los hashes detectan cambios
observados; la contención con editores durante la ventana de reemplazo requiere pruebas
específicas de filesystem en la fase de mantenimiento.

## 9. Estado del checkpoint

Checkpoint de núcleo y regresión superado. Esto no acredita las fases 10–14 ni la aceptación
global de la plataforma. No hay migración de UI ni políticas automáticas habilitadas.

## 10. Próximo paso

Fase 10: API v1 con permisos, contratos de documentos y conocimiento, búsqueda y consulta
fundamentada con evidencia e ingestión controlada a través de los servicios existentes.
