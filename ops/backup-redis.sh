#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 4 ]]; then
  echo "Usage: $0 <host> <port> <password> <output-file>"
  exit 1
fi

host="$1"
port="$2"
password="$3"
output_file="$4"

mkdir -p "$(dirname "$output_file")"
redis-cli -h "$host" -p "$port" -a "$password" --rdb "$output_file"

echo "Redis backup written to $output_file"
