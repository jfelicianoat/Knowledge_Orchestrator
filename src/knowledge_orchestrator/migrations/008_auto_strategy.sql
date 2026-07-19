-- Contrato v2.5 del Broker: los perfiles pueden delegar la estrategia en el
-- meta-router ("auto"). El CHECK de execution_strategy es inline de columna y
-- SQLite no permite alterarlo, así que se rota la columna completa: añadir con
-- el CHECK nuevo, copiar, eliminar la antigua y renombrar. Esto evita
-- reconstruir la tabla (las FKs de topics/captures/notes/workflows hacia
-- profiles quedan intactas) y solo requiere SQLite >= 3.35 (DROP COLUMN),
-- garantizado por Python >= 3.10.
ALTER TABLE profiles ADD COLUMN execution_strategy_v25 TEXT NOT NULL DEFAULT 'single'
    CHECK (execution_strategy_v25 IN ('single', 'mixture_of_agents', 'auto'));
UPDATE profiles SET execution_strategy_v25 = execution_strategy;
ALTER TABLE profiles DROP COLUMN execution_strategy;
ALTER TABLE profiles RENAME COLUMN execution_strategy_v25 TO execution_strategy;
