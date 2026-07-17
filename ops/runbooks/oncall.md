# On-Call And Alerting Runbook

## Alert Sources

Prometheus now evaluates alert rules for:

- backend down
- elevated API 5xx rate
- workflow dead letter growth
- workflow failure rate
- feedback ingest failures

Alert routing starts in Alertmanager with the local `default-log` receiver. Replace that receiver with email, webhook, Slack, or PagerDuty for real production use.

## First Response Checklist

1. Check `/ready` to distinguish database vs Redis availability.
2. Open Grafana and inspect:
   - HTTP request rate and latency
   - workflow failures and retries
   - dead-letter growth
   - LLM latency and token spikes
3. Query `/tenant/audit-events` or `/admin/audit-events` for recent auth, quota, approval, and workflow actions.
4. If workflows are stuck, inspect `GET /jobs/{job_id}` and the worker logs.

## Common Recovery Actions

- `awaiting_human`: approve or reject through `POST /jobs/{job_id}/resume`
- `retry_scheduled`: let the worker retry, or force a recover action after fixing dependencies
- `dead_letter`: inspect checkpoint data, fix the root cause, then recover from a recreated or re-queued job

## Escalation

Escalate immediately if:

- backend scrape is down for more than 2 minutes
- multiple jobs enter dead letter in a 15-minute window
- PostgreSQL or Redis is unavailable
- release approval exists but smoke test still fails after deploy
