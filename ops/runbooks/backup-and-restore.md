# Backup And Restore Runbook

This project supports two operational backup modes:

- Managed services: use cloud-native PostgreSQL and Redis snapshots as the primary mechanism.
- Self-hosted Docker Compose: use the scripts in `ops/` plus persistent volumes.

## PostgreSQL

Create a backup:

```bash
./ops/backup-postgres.sh db.example.com 5432 incident_response incident_user ./ops/artifacts/postgres-$(date +%F-%H%M).dump
```

Restore a backup:

```bash
./ops/restore-postgres.sh db.example.com 5432 incident_response incident_user ./ops/artifacts/postgres-2026-07-13-1200.dump
```

After restoring, run:

```bash
cd backend
python -m alembic upgrade head
```

## Redis

Create a backup snapshot:

```bash
./ops/backup-redis.sh redis.example.com 6379 "$REDIS_PASSWORD" ./ops/artifacts/redis-$(date +%F-%H%M).rdb
```

Restore a self-hosted Redis snapshot:

```bash
./ops/restore-redis.sh ./ops/artifacts/redis-2026-07-13-1200.rdb /var/lib/docker/volumes/multi-agent_redis_data/_data
docker compose restart redis
```

For managed Redis, prefer provider snapshots over manual file restore.

## Restore Validation

After any restore:

1. Run `python -m alembic upgrade head`.
2. Verify `/health`, `/ready`, and `/metrics`.
3. Run `ops/smoke-test.ps1`.
4. Confirm Grafana dashboards and Prometheus alerts are green.
5. Submit one workflow and one feedback ingest request.
