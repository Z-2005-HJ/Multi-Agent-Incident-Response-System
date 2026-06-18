# Database Connection Pool Runbook

Use this runbook when a service reports DatabaseConnectionTimeout, high db_connection_pool_usage, or failed connection acquisition.

1. Confirm whether the incident started after a deployment or config change.
2. Check database connection limit, active connection count, and pool wait time.
3. Compare p95 latency, error_rate, and request throughput before and after the alert.
4. If the change is unsafe, prepare a rollback and require human approval before production action.
5. Verify error_rate and latency return to baseline after mitigation.

