
-- =============================================
-- ms-incidents: Migración 002
-- Tablas para historial y deduplicación de eventos
-- Se ejecuta dentro del schema de cada tenant.
-- =============================================

-- 1. Historial de cambios de estado (IN-05)

CREATE TABLE IF NOT EXISTS incident_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    incident_id UUID NOT NULL
        REFERENCES incidents(id),

    actor_id UUID NOT NULL,

    old_status VARCHAR(20) NOT NULL,

    new_status VARCHAR(20) NOT NULL,

    created_at TIMESTAMP DEFAULT now()
);

-- Índice para consultar el historial de un incidente
CREATE INDEX IF NOT EXISTS idx_incident_events_incident_id
ON incident_events (incident_id, created_at);


-- 2. Eventos SQS ya procesados

CREATE TABLE IF NOT EXISTS processed_events (
    event_id UUID PRIMARY KEY,

    event_type VARCHAR(60) NOT NULL,

    processed_at TIMESTAMP DEFAULT now()
);
