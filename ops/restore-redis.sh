#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <backup-file> <redis-data-dir>"
  exit 1
fi

backup_file="$1"
redis_data_dir="$2"

install -d "$redis_data_dir"
install -m 600 "$backup_file" "$redis_data_dir/dump.rdb"

cat <<'EOF'
Redis snapshot restored to the target data directory.
Restart the Redis service or container after copying the snapshot:
  docker compose restart redis
EOF
