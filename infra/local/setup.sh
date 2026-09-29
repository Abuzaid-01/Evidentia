#!/usr/bin/env bash
# One-time native (no Docker) local setup for macOS + Homebrew.
#   * Postgres 17 on port 5434 (so it never clashes with another Postgres on 5432)
#   * pgvector + PostGIS extensions
#   * Redis on 6379
#   * a NON-superuser app role, so Postgres row-level security is really enforced
#     (superusers bypass RLS, which would hide tenant-isolation bugs locally)
set -euo pipefail

PG_FORMULA="postgresql@17"
PG_PORT="${EVIDENTIA_PG_PORT:-5434}"
APP_ROLE="evidentia"
APP_PASSWORD="${EVIDENTIA_DB_PASSWORD:-evidentia}"
DATABASES=("evidentia" "evidentia_test")

say() { printf "\033[1;32m==>\033[0m %s\n" "$*"; }

command -v brew >/dev/null || { echo "Homebrew is required: https://brew.sh"; exit 1; }

say "Installing packages (skips anything already installed)"
brew list "$PG_FORMULA" >/dev/null 2>&1 || brew install "$PG_FORMULA"
brew list pgvector >/dev/null 2>&1 || brew install pgvector
brew list postgis >/dev/null 2>&1 || brew install postgis
brew list redis >/dev/null 2>&1 || brew install redis

PG_PREFIX="$(brew --prefix "$PG_FORMULA")"
PG_DATA="$(brew --prefix)/var/$PG_FORMULA"
PSQL="$PG_PREFIX/bin/psql"

if [[ ! -f "$PG_DATA/postgresql.conf" ]]; then
  say "Initialising data directory $PG_DATA"
  "$PG_PREFIX/bin/initdb" --locale=C -E UTF-8 "$PG_DATA"
fi

if ! grep -Eq "^port = $PG_PORT" "$PG_DATA/postgresql.conf"; then
  say "Setting $PG_FORMULA port to $PG_PORT"
  sed -i '' -E "s/^#?port = [0-9]+/port = $PG_PORT/" "$PG_DATA/postgresql.conf"
  brew services restart "$PG_FORMULA" >/dev/null
fi

say "Starting services"
brew services start "$PG_FORMULA" >/dev/null || true
brew services start redis >/dev/null || true

for _ in {1..30}; do
  "$PG_PREFIX/bin/pg_isready" -h localhost -p "$PG_PORT" >/dev/null 2>&1 && break
  sleep 1
done

say "Creating role and databases"
"$PSQL" -h localhost -p "$PG_PORT" -d postgres -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$APP_ROLE') THEN
    CREATE ROLE $APP_ROLE LOGIN PASSWORD '$APP_PASSWORD' NOSUPERUSER NOCREATEROLE NOBYPASSRLS;
  END IF;
END
\$\$;
SQL

for db in "${DATABASES[@]}"; do
  if ! "$PSQL" -h localhost -p "$PG_PORT" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$db'" | grep -q 1; then
    "$PSQL" -h localhost -p "$PG_PORT" -d postgres -c "CREATE DATABASE $db OWNER $APP_ROLE"
  fi
  # Extensions need superuser; the app role then only uses them.
  "$PSQL" -h localhost -p "$PG_PORT" -d "$db" -v ON_ERROR_STOP=1 -c \
    "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS postgis; CREATE EXTENSION IF NOT EXISTS pgcrypto;"
done

say "Done."
echo "  DATABASE_URL=postgresql+psycopg://$APP_ROLE:$APP_PASSWORD@localhost:$PG_PORT/evidentia"
echo "  REDIS_URL=redis://localhost:6379/0"
echo "Next: cp .env.example .env  &&  make migrate"
