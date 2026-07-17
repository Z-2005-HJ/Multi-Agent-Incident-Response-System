param(
    [Parameter(Mandatory = $true)][string]$BaseUrl,
    [Parameter(Mandatory = $true)][string]$AdminToken,
    [Parameter(Mandatory = $true)][string]$Summary,
    [Parameter(Mandatory = $true)][string]$RequestedBy,
    [string]$TenantId = "",
    [string]$ConfigScope = "incident-workflow",
    [string]$Environment = "production",
    [int]$ExpiresInHours = 2,
    [switch]$AutoApprove,
    [string]$ApprovedBy = "change-advisory-board",
    [string]$ApprovalNote = "Approved for release"
)

$ErrorActionPreference = "Stop"
$headers = @{ Authorization = "Bearer $AdminToken" }
$query = ""
if ($TenantId) {
    $query = "?tenant_id=$TenantId"
}

$approval = Invoke-RestMethod -Method Post -Uri "$BaseUrl/admin/config-approvals$query" -Headers $headers -ContentType "application/json" -Body (@{
    environment      = $Environment
    config_scope     = $ConfigScope
    summary          = $Summary
    requested_by     = $RequestedBy
    expires_in_hours = $ExpiresInHours
} | ConvertTo-Json)

if ($AutoApprove) {
    $approval = Invoke-RestMethod -Method Post -Uri "$BaseUrl/admin/config-approvals/$($approval.approval_id)/approve" -Headers $headers -ContentType "application/json" -Body (@{
        decided_by = $ApprovedBy
        note       = $ApprovalNote
    } | ConvertTo-Json)
}

$approval
