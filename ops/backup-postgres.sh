#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 5 ]]; then
  echo "Usage: $0 <host> <port> <database> <user> <output-file>"
  exit 1
fi

host="$1"
port="$2"
database="$3"
user="$4"
output_file="$5"

mkdir -p "$(dirname "$output_file")"
pg_dump \
  --host "$host" \
  --port "$port" \
  --username "$user" \
  --format custom \
  --file "$output_file" \
  "$database"

echo "PostgreSQL backup written to $output_file"
