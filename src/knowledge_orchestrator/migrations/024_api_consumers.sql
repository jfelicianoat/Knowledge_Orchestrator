-- Consumidores de la API creados desde la aplicación. Antes solo existían los
-- de KO_API_CLIENTS, y dar acceso de lectura a otra herramienta exigía salir
-- del escritorio y editar variables de entorno.
--
-- La credencial nunca se guarda: solo un hash SHA-256 con sal propia. Se
-- muestra una vez al crearla y, si se pierde, se revoca y se crea otra. Revocar
-- no borra la fila: la actividad registrada sigue teniendo a quién atribuirse.
CREATE TABLE api_consumers (
 consumer_id INTEGER PRIMARY KEY AUTOINCREMENT,
 name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 64),
 scopes_json TEXT NOT NULL,
 token_salt BLOB NOT NULL,
 token_hash BLOB NOT NULL,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 revoked_at TEXT
);
-- Un nombre solo puede estar vivo una vez; tras revocarlo se puede reutilizar.
CREATE UNIQUE INDEX idx_api_consumers_active_name ON api_consumers(name) WHERE revoked_at IS NULL;
