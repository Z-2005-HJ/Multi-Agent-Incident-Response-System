param(
    [ValidateSet("start", "stop", "status", "logs")]
    [string]$Action = "status",
    [string]$ProjectName = "",
    [string]$EnvFile = "ops/compose/mairs.env",
    [string[]]$Service = @()
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $projectRoot $EnvFile

function Import-ComposeEnvironment {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Isolation profile not found: $Path. Copy ops/compose/mairs.env.example to ops/compose/mairs.env first."
    }

    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }
        $parts = $trimmed.Split("=", 2)
        if ($parts.Count -ne 2 -or [string]::IsNullOrWhiteSpace($parts[0])) {
            throw "Invalid environment entry in ${Path}: $line"
        }
        Set-Item -Path "Env:$($parts[0].Trim())" -Value $parts[1].Trim()
    }
}

function Get-ComposeCommand {
    $command = Get-Command docker-compose -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    throw "docker-compose was not found. Install Docker Desktop with Compose support before using this script."
}

Import-ComposeEnvironment -Path $envPath
$compose = Get-ComposeCommand
$resolvedProjectName = $ProjectName
if (-not $resolvedProjectName) {
    $resolvedProjectName = $env:COMPOSE_PROJECT_NAME
}
if (-not $resolvedProjectName) {
    $resolvedProjectName = "mairs"
}

Push-Location $projectRoot
try {
    switch ($Action) {
        "start"  { & $compose -p $resolvedProjectName up --build --detach @Service }
        "stop"   {
            if ($Service.Count) {
                throw "-Service is not supported with stop. Use stop without -Service to remove only this isolated stack."
            }
            & $compose -p $resolvedProjectName down
        }
        "status" { & $compose -p $resolvedProjectName ps @Service }
        "logs"   { & $compose -p $resolvedProjectName logs --tail 200 @Service }
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose command failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
