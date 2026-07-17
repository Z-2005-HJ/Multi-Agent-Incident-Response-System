#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 5 ]]; then
  echo "Usage: $0 <host> <port> <database> <user> <backup-file>"
  exit 1
fi

host="$1"
port="$2"
database="$3"
user="$4"
backup_file="$5"

pg_restore \
  --host "$host" \
  --port "$port" \
  --username "$user" \
  --clean \
  --if-exists \
  --no-owner \
  --dbname "$database" \
  "$backup_file"

echo "PostgreSQL restore completed from $backup_file"
