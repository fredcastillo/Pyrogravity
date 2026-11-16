#!/usr/bin/env bash
set -eo pipefail

psql -X -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
CREATE SCHEMA extensions;
CREATE EXTENSION vector WITH SCHEMA extensions;
CREATE ROLE anon NOLOGIN;
CREATE ROLE authenticated NOLOGIN;
CREATE ROLE service_role NOLOGIN;
SQL

for migration in /migrations/*.sql; do
    psql -X -v ON_ERROR_STOP=1 --single-transaction --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -f "$migration"
done

psql -X -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
\getenv loader_password PYRO_DEV_LOADER_PASSWORD
\getenv reader_password PYRO_DEV_READER_PASSWORD
ALTER ROLE pyrogravity_nasa_loader PASSWORD :'loader_password';
ALTER ROLE pyrogravity_api_reader PASSWORD :'reader_password';
SQL
