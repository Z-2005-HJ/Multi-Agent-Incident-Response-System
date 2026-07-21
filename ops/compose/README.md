# Docker Compose Isolation

Each project running on a shared Docker host needs a unique Compose project
name and a non-overlapping host-port range. The `docker-stack.ps1` wrapper
loads this project's profile only for the current command and always passes the
same project name to Compose.

Compose then isolates the stack automatically:

- containers are named and labelled under `mairs`
- the default network becomes `mairs_default`
- named volumes become `mairs_postgres_data` and `mairs_redis_data`
- exposed ports are assigned from the `15xxx` through `19xxx` range

## Setup

```powershell
Copy-Item ops/compose/mairs.env.example ops/compose/mairs.env
Copy-Item backend/.env.example backend/.env
```

Change the values in `mairs.env` only if one of its assigned ports is already
occupied. Do not reuse the same `COMPOSE_PROJECT_NAME` or port values in the
other Docker projects.

## Commands

```powershell
# Start existing long-running containers without rebuilding images or rerunning migrations.
# On a new machine, this command initializes the stack once.
.\ops\docker-stack.ps1 -Action start

# Rebuild images after changing application dependencies, a Dockerfile, or frontend/backend source.
.\ops\docker-stack.ps1 -Action rebuild

# Show only this stack's containers.
.\ops\docker-stack.ps1 -Action status

# Read the latest logs; add -Service backend or -Service worker to narrow it.
.\ops\docker-stack.ps1 -Action logs

# Stop and remove only this stack's containers and network.
.\ops\docker-stack.ps1 -Action stop
```

`stop` intentionally preserves PostgreSQL and Redis volumes. Removing data is
a separate, explicit operation and is not part of normal stack management.

## Assigned Endpoints

| Service | Default host endpoint |
| --- | --- |
| Frontend | `http://127.0.0.1:15173` |
| Backend | `http://127.0.0.1:18000` |
| PostgreSQL | `127.0.0.1:15432` |
| Redis | `127.0.0.1:16379` |
| Prometheus | `http://127.0.0.1:19090` |
| Alertmanager | `http://127.0.0.1:19093` |
| Grafana | `http://127.0.0.1:13000` |
