#!/bin/sh
set -eu
# Runs at first initialization AND explicitly from the launcher for existing volumes.
# Use the container-local admin socket, so a new .env can repair an old app password.
# Never change the postgres administrator, data, or Django users.
case "$POSTGRES_APP_USER" in
  ''|postgres|pg_*|*[!a-zA-Z0-9_]*|[0-9]*) echo 'Invalid application role name.' >&2; exit 1 ;;
esac
if [ "$POSTGRES_APP_USER" = "$POSTGRES_USER" ]; then
  echo 'Application and administrator roles must be different.' >&2
  exit 1
fi
psql --host=/var/run/postgresql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set=ON_ERROR_STOP=1 \
  --set=app_user="$POSTGRES_APP_USER" --set=app_password="$POSTGRES_APP_PASSWORD" --set=db_name="$POSTGRES_DB" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE', :'app_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user')
\gexec
ALTER ROLE :"app_user" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'app_password';
REVOKE CONNECT, TEMP ON DATABASE :"db_name" FROM PUBLIC;
GRANT CONNECT, TEMP ON DATABASE :"db_name" TO :"app_user";
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO :"app_user";
SQL
