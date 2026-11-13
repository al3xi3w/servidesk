-- Tablas de ms-problems (ver diagrama ER en el documento de diseño).
-- Se ejecuta dentro de cada schema tenant_*.

-- 1. TABLA PRINCIPAL DE PROBLEMAS

CREATE TABLE IF NOT EXISTS problems (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    key VARCHAR(20) NOT NULL UNIQUE,

    title VARCHAR(200) NOT NULL,
    description TEXT,

    status VARCHAR(20) NOT NULL DEFAULT 'new',

    priority VARCHAR(2) NOT NULL,

    root_cause TEXT,

    ci_id UUID,
    owner_id UUID,
    fix_change_id UUID,

    created_at TIMESTAMP NOT NULL DEFAULT
        (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),

    CONSTRAINT chk_problem_priority
        CHECK (priority IN ('P1', 'P2', 'P3', 'P4')),

    CONSTRAINT chk_problem_status
        CHECK (status IN (
            'new',
            'investigating',
            'known_error',
            'resolved',
            'closed'
        )),

    CONSTRAINT chk_problem_root_cause_length
        CHECK (
            root_cause IS NULL
            OR char_length(root_cause) <= 5000
        )
);


-- 2. RELACION ENTRE PROBLEMAS E INCIDENTES
-- Los incidentes pertenecen a otro microservicio.
-- Por eso incident_id NO tiene FK hacia incidents.

CREATE TABLE IF NOT EXISTS problem_incidents (
    problem_id UUID NOT NULL
        REFERENCES problems(id) ON DELETE CASCADE,

    incident_id UUID NOT NULL,

    created_at TIMESTAMP NOT NULL DEFAULT
        (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),

    PRIMARY KEY (problem_id, incident_id)
);


-- 3. BASE DE ERRORES CONOCIDOS (KEDB)

CREATE TABLE IF NOT EXISTS known_errors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    problem_id UUID NOT NULL UNIQUE
        REFERENCES problems(id) ON DELETE CASCADE,

    symptom TEXT NOT NULL,
    workaround TEXT NOT NULL,

    created_at TIMESTAMP NOT NULL DEFAULT
        (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),

    CONSTRAINT chk_known_error_symptom
        CHECK (
            char_length(trim(symptom)) BETWEEN 3 AND 5000
        ),

    CONSTRAINT chk_known_error_workaround
        CHECK (
            char_length(trim(workaround)) BETWEEN 3 AND 5000
        )
);


-- 4. TAREAS ASOCIADAS A PROBLEMAS
-- Tabla preparada para una futura ampliacion.
-- Las tareas no tienen endpoints en PR-01 a PR-07.

CREATE TABLE IF NOT EXISTS problem_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    problem_id UUID NOT NULL
        REFERENCES problems(id) ON DELETE CASCADE,

    title VARCHAR(200) NOT NULL,
    description TEXT,

    status VARCHAR(20) NOT NULL DEFAULT 'pending',

    assignee_id UUID,

    created_at TIMESTAMP NOT NULL DEFAULT
        (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),

    CONSTRAINT chk_problem_task_status
        CHECK (status IN (
            'pending',
            'in_progress',
            'completed'
        ))
);


-- 5. INDICES PARA CONSULTAS FRECUENTES

CREATE INDEX IF NOT EXISTS idx_problems_status
ON problems (status);

CREATE INDEX IF NOT EXISTS idx_problems_priority
ON problems (priority);

CREATE INDEX IF NOT EXISTS idx_problems_owner
ON problems (owner_id);

CREATE INDEX IF NOT EXISTS idx_problems_ci
ON problems (ci_id);

CREATE INDEX IF NOT EXISTS idx_problems_created
ON problems (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_problem_incidents_incident
ON problem_incidents (incident_id);

CREATE INDEX IF NOT EXISTS idx_problem_tasks_problem
ON problem_tasks (problem_id);