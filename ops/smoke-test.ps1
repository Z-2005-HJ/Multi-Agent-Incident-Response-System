param(
    [Parameter(Mandatory = $true)][string]$BaseUrl,
    [string]$ApiToken = "",
    [string]$ReleaseApprovalId = ""
)

$ErrorActionPreference = "Stop"

function Invoke-Json {
    param(
        [string]$Method,
        [string]$Uri,
        [hashtable]$Headers = @{},
        [object]$Body = $null
    )

    $params = @{
        Method  = $Method
        Uri     = $Uri
        Headers = $Headers
    }

    if ($null -ne $Body) {
        $params["ContentType"] = "application/json"
        $params["Body"] = ($Body | ConvertTo-Json -Depth 10)
    }

    return Invoke-RestMethod @params
}

$headers = @{}
if ($ApiToken) {
    $headers["Authorization"] = "Bearer $ApiToken"
}
if ($ReleaseApprovalId) {
    $headers["X-Release-Approval"] = $ReleaseApprovalId
}

$health = Invoke-Json -Method Get -Uri "$BaseUrl/health"
$ready = Invoke-Json -Method Get -Uri "$BaseUrl/ready"
$llmStatus = Invoke-Json -Method Get -Uri "$BaseUrl/llm/status"
$opsStatus = $null
$incidents = @()
if ($ApiToken) {
    $opsStatus = Invoke-Json -Method Get -Uri "$BaseUrl/ops/status" -Headers $headers
    $incidents = Invoke-Json -Method Get -Uri "$BaseUrl/incidents" -Headers $headers
}
$metrics = Invoke-WebRequest -Method Get -Uri "$BaseUrl/metrics"

if ($health.status -ne "ok") { throw "Health check failed." }
if ($ready.status -ne "ready") { throw "Readiness check failed." }
if (-not $llmStatus.mode) { throw "LLM status payload missing mode." }
if ($ApiToken -and -not $opsStatus.operations_mode) { throw "Ops status payload missing operations_mode." }
if (-not $metrics.Content.Contains("incident_response_workflow_runs_total")) {
    throw "Metrics output missing workflow run metric."
}

Write-Host "Smoke test passed."
if ($ApiToken) {
    Write-Host ("Incidents listed: {0}" -f $incidents.Count)
}
