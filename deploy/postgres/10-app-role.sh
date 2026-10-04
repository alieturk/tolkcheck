#!/bin/sh
# Runs once, when the postgres container initialises an empty data directory
# (docker-entrypoint-initdb.d). Creates the least-privilege role the API and
# worker connect as (BIO2 5.18): it can read and write rows, but cannot create
# or drop tables, roles or extensions. Schema changes are made only by the
# one-off `migrate` service, which connects as POSTGRES_USER (the owner).
set -eu

: "${APP_DB_PASSWORD:?APP_DB_PASSWORD must be set}"

psql -v ON_ERROR_STOP=1 \
     -v app_password="$APP_DB_PASSWORD" \
     -v owner="$POSTGRES_USER" \
     -v db="$POSTGRES_DB" \
     --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
CREATE ROLE tolkcheck_app LOGIN PASSWORD :'app_password';
GRANT CONNECT ON DATABASE :"db" TO tolkcheck_app;
GRANT USAGE ON SCHEMA public TO tolkcheck_app;

-- Tables and sequences created later by the migrations (as the owner) are
-- granted to the app role automatically.
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO tolkcheck_app;
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO tolkcheck_app;
SQL
