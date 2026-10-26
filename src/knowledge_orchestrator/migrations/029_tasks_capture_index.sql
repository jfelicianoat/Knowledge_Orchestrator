-- La lista de Trabajo busca la última tarea de cada documento (26-oct-2026).
-- Sin este índice SQLite recorría la tabla `tasks` entera por cada documento:
-- con 765 documentos y ~2000 tareas de ~75 KB eran 6–12 s cada 2 s en el hilo
-- de la ventana, que se quedaba bloqueada. Con el índice, 0,07 s.
CREATE INDEX IF NOT EXISTS idx_tasks_capture_latest
    ON tasks(capture_id, updated_at DESC, created_at DESC, task_id DESC);
