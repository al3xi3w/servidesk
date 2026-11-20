-- Tablas de ms-cmdb (db_cmdb). Se ejecuta dentro de cada schema tenant_*.
-- No usar punto y coma dentro de comentarios: migrate.py separa sentencias por ese caracter.

CREATE TABLE IF NOT EXISTS ci_types (
  id SERIAL PRIMARY KEY,
  name VARCHAR(60) NOT NULL,
  CONSTRAINT ci_types_name_key UNIQUE (name)
);

CREATE TABLE IF NOT EXISTS configuration_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  type_id INT NOT NULL REFERENCES ci_types (id),
  name VARCHAR(150) NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'operational',
  environment VARCHAR(10) NOT NULL,
  version VARCHAR(50),
  owner_team_id UUID,
  attributes JSONB NOT NULL DEFAULT CAST('{}' AS jsonb),
  created_at TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
  updated_at TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
  CONSTRAINT ci_status_chk CHECK (status IN ('operational', 'degraded', 'down', 'retired')),
  CONSTRAINT ci_environment_chk CHECK (environment IN ('prod', 'qa', 'dev'))
);

CREATE INDEX IF NOT EXISTS ci_status_idx ON configuration_items (status);
CREATE INDEX IF NOT EXISTS ci_environment_idx ON configuration_items (environment);
CREATE INDEX IF NOT EXISTS ci_type_idx ON configuration_items (type_id);
CREATE INDEX IF NOT EXISTS ci_owner_team_idx ON configuration_items (owner_team_id);
CREATE INDEX IF NOT EXISTS ci_created_at_idx ON configuration_items (created_at DESC);
CREATE INDEX IF NOT EXISTS ci_updated_at_idx ON configuration_items (updated_at DESC);

CREATE TABLE IF NOT EXISTS ci_relations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_ci_id UUID NOT NULL REFERENCES configuration_items (id) ON DELETE CASCADE,
  target_ci_id UUID NOT NULL REFERENCES configuration_items (id) ON DELETE CASCADE,
  relation VARCHAR(20) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
  CONSTRAINT ci_relations_unique UNIQUE (source_ci_id, target_ci_id, relation),
  CONSTRAINT ci_relations_not_self CHECK (source_ci_id <> target_ci_id),
  CONSTRAINT ci_relations_relation_chk CHECK (relation IN ('depends_on', 'runs_on', 'connects_to'))
);

CREATE INDEX IF NOT EXISTS ci_relations_source_idx ON ci_relations (source_ci_id);
CREATE INDEX IF NOT EXISTS ci_relations_target_idx ON ci_relations (target_ci_id);

-- Historial de cambios por campo (API, consumidor de ChangeImplemented)
CREATE TABLE IF NOT EXISTS ci_history (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  ci_id UUID NOT NULL REFERENCES configuration_items (id) ON DELETE CASCADE,
  field VARCHAR(50) NOT NULL,
  old_value TEXT,
  new_value TEXT,
  actor_id UUID,
  source VARCHAR(30) NOT NULL DEFAULT 'api',
  change_id UUID,
  changed_at TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
);

CREATE INDEX IF NOT EXISTS ci_history_ci_idx ON ci_history (ci_id, changed_at DESC);

-- Idempotencia de consumidores SQS (decision D10)
CREATE TABLE IF NOT EXISTS processed_events (
  event_id UUID PRIMARY KEY,
  event_type VARCHAR(60) NOT NULL,
  processed_at TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
)
