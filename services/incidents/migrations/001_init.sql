-- Tablas de ms-incidents. Se ejecuta dentro de cada schema tenant_*.
CREATE TABLE IF NOT EXISTS sla_policies (
  id SERIAL PRIMARY KEY,
  priority VARCHAR(2) NOT NULL,
  response_minutes INT NOT NULL,
  resolution_minutes INT NOT NULL
);
CREATE TABLE IF NOT EXISTS incidents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  key VARCHAR(20) UNIQUE NOT NULL,
  title VARCHAR(200) NOT NULL,
  description TEXT,
  status VARCHAR(20) NOT NULL DEFAULT 'new',
  impact VARCHAR(10),
  urgency VARCHAR(10),
  priority VARCHAR(2),
  sla_policy_id INT REFERENCES sla_policies(id),
  sla_due_at TIMESTAMP,
  sla_breached BOOLEAN DEFAULT FALSE,
  reporter_id UUID,
  assignee_id UUID,
  team_id UUID,
  ci_id UUID,
  problem_id UUID,
  channel VARCHAR(10) DEFAULT 'portal',
  created_at TIMESTAMP DEFAULT now(),
  resolved_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS incident_comments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  incident_id UUID REFERENCES incidents(id),
  author_id UUID,
  body TEXT,
  internal BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMP DEFAULT now()
)
