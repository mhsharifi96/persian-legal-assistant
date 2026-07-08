#!/usr/bin/env bash
# Web entrypoint: wait for the database, apply migrations, then run the command.
set -euo pipefail

wait_for_tcp() {
  local host="$1" port="$2" attempts="${3:-60}"
  echo "Waiting for ${host}:${port}..."
  for _ in $(seq "$attempts"); do
    if python -c "import socket,sys; s=socket.socket(); s.settimeout(2); sys.exit(0 if s.connect_ex(('${host}', ${port}))==0 else 1)"; then
      echo "${host}:${port} is up."
      return 0
    fi
    sleep 1
  done
  echo "Timed out waiting for ${host}:${port}" >&2
  return 1
}

if [ "${DB_ENGINE:-}" = "postgres" ]; then
  wait_for_tcp "${DB_HOST:-postgres}" "${DB_PORT:-5432}"
fi

echo "Applying migrations..."
python manage.py migrate --noinput

exec "$@"
