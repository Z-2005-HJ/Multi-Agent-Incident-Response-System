# Release And Rollback Runbook

## Pre-Release

1. Update `.env.production` from `.env.production.example`.
2. Run `ops/preflight.ps1 -ComposeEnvPath .env.production`.
3. Run backend tests and frontend build in CI.
4. Build and publish the backend and frontend images.
5. Create a release approval:

```powershell
.\ops\request-release-approval.ps1 `
  -BaseUrl https://api.example.com `
  -AdminToken $env:APP_ADMIN_API_TOKEN `
  -Summary "Release 2026-07-13" `
  -RequestedBy "ops-owner" `
  -AutoApprove
```

## Deploy

1. Pull the new images or update the current checkout.
2. Run migrations:

```bash
docker compose run --rm migrate
```

3. Restart the stack:

```bash
docker compose up -d --build
```

4. Execute smoke validation:

```powershell
.\ops\smoke-test.ps1 -BaseUrl https://api.example.com -ApiToken $tenantApiToken
```

## Rollback

Rollback should prefer image rollback plus workflow pause over ad hoc edits:

1. Stop new release traffic at the load balancer or maintenance layer if needed.
2. Re-deploy the previous known-good image tag.
3. Re-run `docker compose up -d`.
4. Re-run `ops/smoke-test.ps1`.
5. If the migration introduced an incompatible schema change, restore PostgreSQL from backup and re-run Alembic to the desired revision.

## When To Use Release Approval

In `APP_OPERATIONS_MODE=production`, runtime workflow execution requires `X-Release-Approval`.
Use a fresh approval for:

- first deploy of a new version
- hotfix rollouts
- emergency recover and retry windows after an incident
