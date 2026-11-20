-- Tablas globales de ms-identity (schema public de db_identity).
-- public.tenants es la unica tabla que resuelve el tenant a partir de un dato del cliente (tenant_code del login).
CREATE TABLE IF NOT EXISTS public.tenants (
  code VARCHAR(30) PRIMARY KEY,
  schema_name VARCHAR(63) NOT NULL UNIQUE,
  name VARCHAR(150) NOT NULL,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
  CONSTRAINT tenants_code_chk CHECK (code ~ '^[a-z0-9_]{2,30}$'),
  CONSTRAINT tenants_schema_chk CHECK (schema_name = 'tenant_' || code)
);
