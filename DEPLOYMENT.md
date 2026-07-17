# Deployment Guide

This project can now run as a public demo deployment with a containerized
frontend, a FastAPI backend, optional demo token protection, and a local
observability stack with Prometheus and Grafana, plus PostgreSQL and Redis for
durable workflow execution.

For a formal public SaaS deployment, the repo now also includes:

- production startup safety checks
- trusted host enforcement and baseline security headers
- request body size limits
- IP-based rate limiting
- Alembic migration scaffolding for PostgreSQL schema management
- tenant-user session login and RBAC scaffolding
- a GitHub Actions CI workflow for tests, migrations, and frontend build

## What This Version Supports

- Frontend served by Nginx
- Backend served by Uvicorn on `0.0.0.0:8000`
- Reverse proxy from frontend `/api/*` to backend
- Configurable CORS origins
- Optional demo API token for incident and feedback endpoints
- PostgreSQL persistence for incident runs, traces, approvals, and workflow jobs
- Redis-backed async execution with a worker, run locks, delayed retry, and DLQ
- Multi-tenant SaaS API keys with tenant-scoped request and workflow quotas
- Tenant user login sessions with RBAC role-to-scope enforcement
- Audit events for tenant, key, workflow, feedback, and approval activity
- Production config approvals and release-gate enforcement in production mode
- Ops mode switch: `demo`, `ops`, or `production`
- Health endpoint: `/health`
- Readiness endpoint: `/ready`
- Metrics endpoint: `/metrics`
- Async workflow endpoints: `POST /incidents/submit`, `GET /jobs/{job_id}`
- Grafana provisioning with a Prometheus datasource and starter dashboard
- Prometheus alert rules and Alertmanager routing scaffolding

## Environment

Copy [backend/.env.example](/D:/APP/pyCharm/JupyterProject/multi-Agent/Multi-Agent%20Incident%20Response%20System/backend/.env.example)
to `backend/.env` and update values as needed.

For a production compose deployment, also copy
[.env.production.example](/D:/APP/pyCharm/JupyterProject/multi-Agent/Multi-Agent%20Incident%20Response%20System/.env.production.example)
to `.env.production`.

Key variables:

- `LLM_MODE=mock` keeps the demo self-contained
- `APP_CORS_ORIGINS` controls allowed frontend origins
- `APP_ALLOWED_HOSTS` controls trusted `Host` headers
- `APP_OPERATIONS_MODE` selects `demo`, `ops`, or `production`
- `APP_ADMIN_API_TOKEN` protects SaaS admin and governance endpoints
- `APP_API_KEY_PEPPER` salts tenant API key hashes at rest
- `APP_DATABASE_URL` points the backend and worker at PostgreSQL
- `APP_AUTO_CREATE_SCHEMA=false` should be used in production after migrations are in place
- `APP_REDIS_URL` enables the async execution layer
- `APP_JOB_MAX_RETRIES`, `APP_JOB_RETRY_DELAY_SECONDS`, and
  `APP_RUN_LOCK_TTL_SECONDS` tune worker retry behavior
- `APP_MAX_REQUEST_BODY_BYTES` limits oversized request payloads
- `APP_RATE_LIMIT_ENABLED`, `APP_RATE_LIMIT_REQUESTS`, and
  `APP_RATE_LIMIT_WINDOW_SECONDS` control public API abuse protection
- `DEMO_API_TOKEN` enables simple bearer-token protection for runtime endpoints

If `DEMO_API_TOKEN` is set, the frontend must build with the same token via
`VITE_DEMO_API_TOKEN`.

For SaaS mode, issue tenant keys through:

- `POST /admin/tenants`
- `POST /admin/tenants/{tenant_id}/keys`

Protect those endpoints with `APP_ADMIN_API_TOKEN`.

To bootstrap tenant users for interactive login:

- `POST /admin/tenants/{tenant_id}/users`
- `POST /auth/login`
- `GET /auth/me`
- `GET /tenant/users`
- `POST /auth/logout`

Tenant admins can also operate day-2 user and credential management through:

- `POST /tenant/users/{user_id}/role`
- `POST /tenant/users/{user_id}/suspend`
- `POST /tenant/users/{user_id}/activate`
- `POST /tenant/users/{user_id}/password-reset`
- `GET /tenant/sessions`
- `POST /tenant/sessions/{session_id}/revoke`
- `GET /tenant/api-keys`
- `POST /tenant/api-keys/{key_id}/revoke`

## Database Migrations

Development mode can auto-create tables when `APP_AUTO_CREATE_SCHEMA=true`.

For production, disable auto schema creation and run migrations explicitly:

```powershell
cd backend
..\.venv\Scripts\python.exe -m alembic upgrade head
```

The initial Alembic revision lives in:

- [backend/alembic/versions/20260712_0001_initial_schema.py](/D:/APP/pyCharm/JupyterProject/multi-Agent/Multi-Agent%20Incident%20Response%20System/backend/alembic/versions/20260712_0001_initial_schema.py)

## Local Demo Deployment

Run:

```powershell
docker-compose up --build
```

Run explicit migrations with:

```powershell
docker-compose run --rm migrate
```

Services:

- Frontend: `http://127.0.0.1:5173`
- Backend health: `http://127.0.0.1:8000/health`
- Backend readiness: `http://127.0.0.1:8000/ready`
- Backend metrics: `http://127.0.0.1:8000/metrics`
- PostgreSQL: `127.0.0.1:5432`
- Redis: `127.0.0.1:6379`
- Prometheus: `http://127.0.0.1:9090`
- Alertmanager: `http://127.0.0.1:9093`
- Grafana: `http://127.0.0.1:3000`

Grafana default credentials:

- Username: `admin`
- Password: `admin`

The frontend calls the backend through `/api`, so the browser does not need a
hard-coded backend hostname in the deployed demo.

The observability / tracing & evaluation layer remains part of the system.
This change adds Prometheus and Grafana on top of the existing trace and eval
capabilities rather than removing them.

The compose stack now also starts a dedicated `worker` service. Long-running
incident workflows can be submitted with `POST /incidents/submit`; the worker
pulls jobs from Redis, enforces a per-incident run lock, retries failed runs
with delay, and moves exhausted jobs into the dead letter queue.

The backend image now includes Alembic files, so the dedicated `migrate`
service can run schema upgrades inside the same container image used by the API
and worker.

When `APP_OPERATIONS_MODE=production`, `POST /incidents/run` and
`POST /incidents/submit` require an approved release gate header:

- `X-Release-Approval: cfg_...`

Create and approve that gate through:

- `POST /admin/config-approvals`
- `POST /admin/config-approvals/{approval_id}/approve`

## Public Production Checklist

Complete these before exposing the system on the internet:

1. Rotate all infrastructure credentials.
   Set non-default values for `POSTGRES_PASSWORD`, `REDIS_PASSWORD`,
   `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD`, `APP_ADMIN_API_TOKEN`, and
   `APP_API_KEY_PEPPER`.
2. Set production runtime controls.
   Use `APP_OPERATIONS_MODE=production`, `APP_AUTO_CREATE_SCHEMA=false`,
   explicit `APP_CORS_ORIGINS`, and explicit `APP_ALLOWED_HOSTS`.
3. Run PostgreSQL migrations before starting the API.
   Use `alembic upgrade head`.
4. Keep rate limiting enabled.
   Confirm `APP_RATE_LIMIT_ENABLED=true` and tune the request/window settings
   for your traffic profile.
5. Put the stack behind TLS.
   Terminate HTTPS at Nginx, Caddy, a cloud load balancer, or your ingress.
6. Configure persistent storage and backups.
   PostgreSQL backups and Redis durability are external operational
   responsibilities.
7. Verify observability.
   Check `/metrics`, Prometheus targets, Grafana datasource provisioning, and
   alerting for API 5xx, queue failures, and dead-letter growth.
8. Disable demo access patterns.
   Do not set `DEMO_API_TOKEN` in production SaaS mode.
9. Bootstrap the first tenant admin user.
   Use the platform admin token to create at least one tenant user with role
   `admin`, then test `/auth/login` and `/auth/me`.
10. Wire CI/CD to your deployment process.
    The repo now includes `.github/workflows/ci.yml`; require it to pass before
    release.

## Operational Scripts

The repo now includes deploy and day-2 operations scripts under:

- [ops/preflight.ps1](/D:/APP/pyCharm/JupyterProject/multi-Agent/Multi-Agent%20Incident%20Response%20System/ops/preflight.ps1)
- [ops/smoke-test.ps1](/D:/APP/pyCharm/JupyterProject/multi-Agent/Multi-Agent%20Incident%20Response%20System/ops/smoke-test.ps1)
- [ops/bootstrap-tenant.ps1](/D:/APP/pyCharm/JupyterProject/multi-Agent/Multi-Agent%20Incident%20Response%20System/ops/bootstrap-tenant.ps1)
- [ops/request-release-approval.ps1](/D:/APP/pyCharm/JupyterProject/multi-Agent/Multi-Agent%20Incident%20Response%20System/ops/request-release-approval.ps1)
- [ops/backup-postgres.sh](/D:/APP/pyCharm/JupyterProject/multi-Agent/Multi-Agent%20Incident%20Response%20System/ops/backup-postgres.sh)
- [ops/restore-postgres.sh](/D:/APP/pyCharm/JupyterProject/multi-Agent/Multi-Agent%20Incident%20Response%20System/ops/restore-postgres.sh)
- [ops/backup-redis.sh](/D:/APP/pyCharm/JupyterProject/multi-Agent/Multi-Agent%20Incident%20Response%20System/ops/backup-redis.sh)
- [ops/restore-redis.sh](/D:/APP/pyCharm/JupyterProject/multi-Agent/Multi-Agent%20Incident%20Response%20System/ops/restore-redis.sh)

Recommended flow:

1. Run `ops/preflight.ps1` before the first production cutover.
2. Use `ops/bootstrap-tenant.ps1` to create the first tenant, admin user, and
   primary API key.
3. Use `ops/request-release-approval.ps1` to issue and approve production
   release gates.
4. Run `ops/smoke-test.ps1` after every deploy, rollback, and restore event.

## Runbooks

Detailed operations runbooks now live in:

- [ops/runbooks/backup-and-restore.md](/D:/APP/pyCharm/JupyterProject/multi-Agent/Multi-Agent%20Incident%20Response%20System/ops/runbooks/backup-and-restore.md)
- [ops/runbooks/release-and-rollback.md](/D:/APP/pyCharm/JupyterProject/multi-Agent/Multi-Agent%20Incident%20Response%20System/ops/runbooks/release-and-rollback.md)
- [ops/runbooks/oncall.md](/D:/APP/pyCharm/JupyterProject/multi-Agent/Multi-Agent%20Incident%20Response%20System/ops/runbooks/oncall.md)

## Alerting

Prometheus now loads:

- [monitoring/prometheus/alerts.yml](/D:/APP/pyCharm/JupyterProject/multi-Agent/Multi-Agent%20Incident%20Response%20System/monitoring/prometheus/alerts.yml)

Alertmanager now loads:

- [monitoring/alertmanager/alertmanager.yml](/D:/APP/pyCharm/JupyterProject/multi-Agent/Multi-Agent%20Incident%20Response%20System/monitoring/alertmanager/alertmanager.yml)

The default Alertmanager receiver is intentionally minimal. Replace it with
your production email, webhook, Slack, or PagerDuty integration before go-live.

## Public Demo Notes

For a public server or VM, this version is suitable as a demo deployment, not
as a full production system.

Recommended minimum setup:

- 1 Linux host with Docker and Docker Compose
- One public domain or IP
- TLS terminated by Nginx, Caddy, or a cloud load balancer
- `DEMO_API_TOKEN` enabled if the demo is exposed to the internet
- Rotate the default PostgreSQL, Redis, and Grafana credentials before exposure
- Rotate `APP_ADMIN_API_TOKEN` and `APP_API_KEY_PEPPER` before exposure
- Persist Grafana data and rotate admin credentials before sharing the stack

## Still Missing Before Production

- Real end-user authentication and RBAC or SSO/IdP integration
- Centralized log shipping and alert routing to your production tooling
- Backup/restore drills and DB operational runbooks
- Formal CI/CD gates for migrations, tests, image signing, and deployment rollout
- Commercial/legal/compliance controls outside the repo itself
