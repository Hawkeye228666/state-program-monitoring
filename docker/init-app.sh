#!/bin/sh
set -eu
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set=ON_ERROR_STOP=1 \
  --set=app_user="$POSTGRES_APP_USER" --set=app_password="$POSTGRES_APP_PASSWORD" --set=db_name="$POSTGRES_DB" <<'SQL'
CREATE ROLE :"app_user" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'app_password';
REVOKE CONNECT, TEMP ON DATABASE :"db_name" FROM PUBLIC;
GRANT CONNECT, TEMP ON DATABASE :"db_name" TO :"app_user";
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO :"app_user";
SQL
