-- Modelo para las tareas que exigen JSON conforme a esquema (extracción de
-- afirmaciones, comparación de evidencia y consultas fundamentadas). Es
-- distinto del modelo que redacta el apunte: uno escribe prosa y el otro tiene
-- que devolver una estructura exacta, y un modelo bueno redactando puede ser
-- inservible aquí. Vacío = lo elige la aplicación.
ALTER TABLE profiles ADD COLUMN analysis_model TEXT NOT NULL DEFAULT '';

-- Memoria de lo que ya salió mal. Un modelo puede cumplir todos los filtros del
-- catálogo (propósito general, sin razonamiento, tamaño razonable) y aun así
-- entrar en bucle o inventar citas: eso solo se sabe ejecutándolo. Lo que falló
-- una vez deja de proponerse solo; el usuario siempre puede fijarlo a mano.
CREATE TABLE analysis_model_failures (
 model TEXT PRIMARY KEY,
 error_code TEXT NOT NULL,
 message TEXT NOT NULL DEFAULT '',
 failures INTEGER NOT NULL DEFAULT 1 CHECK(failures > 0),
 first_failed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 last_failed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
