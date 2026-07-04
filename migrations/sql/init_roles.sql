-- DB bootstrap: run once as the cluster superuser (docker-entrypoint-initdb.d in compose,
-- or `psql` in CI) BEFORE Alembic. Creates the app + bypass roles and the pgvector extension.
--
-- Role model (dev): the DB is owned by `cs_owner` (the entrypoint superuser in dev). The app
-- connects as `cs_app` (NOSUPERUSER, NOBYPASSRLS) so RLS is always enforced; ops uses
-- `cs_bypass` (BYPASSRLS) on its own connection. Migrations run as the owner.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cs_app') THEN
        CREATE ROLE cs_app LOGIN PASSWORD 'cs_app_pw' NOSUPERUSER NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cs_bypass') THEN
        CREATE ROLE cs_bypass LOGIN PASSWORD 'cs_bypass_pw' NOSUPERUSER BYPASSRLS;
    END IF;
END $$;

CREATE EXTENSION IF NOT EXISTS vector;

GRANT CONNECT ON DATABASE cs_agent TO cs_app, cs_bypass;
