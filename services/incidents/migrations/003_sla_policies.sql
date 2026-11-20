-- ms-incidents: Migración 003
-- Políticas SLA base (P1 4 h, P2 8 h, P3 24 h, P4 72 h), las mismas del modo demo del frontend.
-- createIncident y el consumidor de CIStatusChanged las necesitan. Idempotente.

INSERT INTO sla_policies (priority, response_minutes, resolution_minutes)
SELECT v.priority, v.response_minutes, v.resolution_minutes
FROM (VALUES
  (1, 'P1', 15, 240),
  (2, 'P2', 30, 480),
  (3, 'P3', 120, 1440),
  (4, 'P4', 480, 4320)
) AS v (ord, priority, response_minutes, resolution_minutes)
WHERE NOT EXISTS (SELECT 1 FROM sla_policies s WHERE s.priority = v.priority)
ORDER BY v.ord;

-- Vínculo rápido incidente -> problema (lo usa incidents-kedb-q)
CREATE INDEX IF NOT EXISTS idx_incidents_problem_id ON incidents (problem_id);
CREATE INDEX IF NOT EXISTS idx_incidents_ci_created ON incidents (ci_id, created_at DESC)
