param(
    [string]$ComposeEnvPath = ".env.production",
    [string]$BaseUrl = ""
)

$ErrorActionPreference = "Stop"

function Assert-EnvValue {
    param(
        [hashtable]$Values,
        [string]$Key
    )

    if (-not $Values.ContainsKey($Key) -or [string]::IsNullOrWhiteSpace($Values[$Key])) {
        throw "Missing required setting: $Key"
    }
}

function Read-EnvFile {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        throw "Env file not found: $Path"
    }

    $values = @{}
    foreach ($line in Get-Content $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }
        $parts = $trimmed.Split("=", 2)
        if ($parts.Count -eq 2) {
            $values[$parts[0].Trim()] = $parts[1].Trim()
        }
    }
    return $values
}

$envValues = Read-EnvFile -Path $ComposeEnvPath

$requiredKeys = @(
    "POSTGRES_PASSWORD",
    "REDIS_PASSWORD",
    "GRAFANA_ADMIN_PASSWORD",
    "APP_ADMIN_API_TOKEN",
    "APP_API_KEY_PEPPER",
    "APP_DATABASE_URL",
    "APP_REDIS_URL",
    "APP_ALLOWED_HOSTS",
    "APP_CORS_ORIGINS"
)

foreach ($key in $requiredKeys) {
    Assert-EnvValue -Values $envValues -Key $key
}

if ($envValues["APP_OPERATIONS_MODE"] -ne "production") {
    throw "APP_OPERATIONS_MODE must be set to production."
}

if ($envValues["APP_AUTO_CREATE_SCHEMA"] -ne "false") {
    throw "APP_AUTO_CREATE_SCHEMA must be false in production."
}

if ($envValues["APP_TRUST_PROXY_HEADERS"] -ne "true") {
    throw "APP_TRUST_PROXY_HEADERS should be true behind a reverse proxy or cloud load balancer."
}

if ($BaseUrl) {
    $health = Invoke-RestMethod -Method Get -Uri "$BaseUrl/health"
    $ready = Invoke-RestMethod -Method Get -Uri "$BaseUrl/ready"
    $metrics = Invoke-WebRequest -Method Get -Uri "$BaseUrl/metrics"

    if ($health.status -ne "ok") {
        throw "Health endpoint returned an unexpected payload."
    }
    if ($ready.status -ne "ready") {
        throw "Ready endpoint returned an unexpected payload."
    }
    if (-not $metrics.Content.Contains("incident_response_http_requests_total")) {
        throw "Metrics endpoint does not contain expected Prometheus counters."
    }
}

Write-Host "Preflight checks passed."
