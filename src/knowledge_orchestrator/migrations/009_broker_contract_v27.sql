-- Opciones vigentes del contrato Broker 2.7 que son relevantes para el flujo durable
-- del Orchestrator. Los defaults conservan el comportamiento anterior.
ALTER TABLE profiles ADD COLUMN long_context TEXT NOT NULL DEFAULT 'fail'
    CHECK (long_context IN ('fail', 'map_reduce'));
ALTER TABLE profiles ADD COLUMN prompt_compression TEXT
    CHECK (prompt_compression IS NULL OR prompt_compression IN ('off', 'light', 'medium', 'aggressive'));
