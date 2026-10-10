-- Límite de tiempo de la redacción con consenso o «Automático según la tarea».
-- Con 600 s, el perfil por defecto falló con un documento de 690 bytes
-- (prueba de uso real, 8-oct-2026): el Broker eligió consenso secuencial entre
-- cuatro modelos locales de 27–33B y uno seguía cargando desde disco al
-- vencer el plazo (TASK_TIMEOUT). El análisis semántico ya usa 1800 s por la
-- misma causa. La interfaz no permite cambiar este valor, así que solo se
-- suben los perfiles que siguen en el valor de fábrica.
UPDATE profiles SET consensus_timeout_seconds = 1800 WHERE consensus_timeout_seconds = 600;
