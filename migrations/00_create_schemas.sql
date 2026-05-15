-- PMIS Refactor — Step 1 of cutover (after pg_dump snapshot)
-- Creates the four per-service schemas and grants application + DDL roles.
-- Run as a Postgres superuser.

CREATE SCHEMA IF NOT EXISTS users;
CREATE SCHEMA IF NOT EXISTS project;
CREATE SCHEMA IF NOT EXISTS notification;   -- empty post-refactor (no owned tables)
CREATE SCHEMA IF NOT EXISTS masters;

-- Application role: read-write on all tables, no DDL.
GRANT USAGE ON SCHEMA users, project, notification, masters TO pmis_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA users, project, notification, masters TO pmis_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA users, project, notification, masters TO pmis_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA users GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO pmis_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA project GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO pmis_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA notification GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO pmis_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA masters GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO pmis_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA users GRANT USAGE, SELECT ON SEQUENCES TO pmis_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA project GRANT USAGE, SELECT ON SEQUENCES TO pmis_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA notification GRANT USAGE, SELECT ON SEQUENCES TO pmis_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA masters GRANT USAGE, SELECT ON SEQUENCES TO pmis_app;

-- DDL role: full DDL (used by `alembic upgrade head` via DATABASE_URL_MIGRATIONS).
GRANT USAGE, CREATE ON SCHEMA users, project, notification, masters TO pmis_ddl;
