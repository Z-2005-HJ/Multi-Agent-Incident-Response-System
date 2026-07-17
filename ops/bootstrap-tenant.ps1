param(
    [Parameter(Mandatory = $true)][string]$BaseUrl,
    [Parameter(Mandatory = $true)][string]$AdminToken,
    [Parameter(Mandatory = $true)][string]$TenantName,
    [Parameter(Mandatory = $true)][string]$AdminEmail,
    [Parameter(Mandatory = $true)][string]$AdminPassword,
    [string]$AdminFullName = "Tenant Admin",
    [int]$RequestQuotaLimit = 10000,
    [int]$WorkflowQuotaLimit = 2000,
    [int]$QuotaWindowMinutes = 1440
)

$ErrorActionPreference = "Stop"
$headers = @{ Authorization = "Bearer $AdminToken" }

$tenant = Invoke-RestMethod -Method Post -Uri "$BaseUrl/admin/tenants" -Headers $headers -ContentType "application/json" -Body (@{
    tenant_name          = $TenantName
    request_quota_limit  = $RequestQuotaLimit
    workflow_quota_limit = $WorkflowQuotaLimit
    quota_window_minutes = $QuotaWindowMinutes
} | ConvertTo-Json)

$user = Invoke-RestMethod -Method Post -Uri "$BaseUrl/admin/tenants/$($tenant.tenant_id)/users" -Headers $headers -ContentType "application/json" -Body (@{
    email     = $AdminEmail
    full_name = $AdminFullName
    role      = "admin"
    password  = $AdminPassword
} | ConvertTo-Json)

$key = Invoke-RestMethod -Method Post -Uri "$BaseUrl/admin/tenants/$($tenant.tenant_id)/keys" -Headers $headers -ContentType "application/json" -Body (@{
    label = "primary"
} | ConvertTo-Json)

[PSCustomObject]@{
    tenant_id = $tenant.tenant_id
    user_id   = $user.user_id
    api_key   = $key.api_key
}
