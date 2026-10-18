# Проверка этапа 1. Запуск из корня проекта после docker compose up -d --build:
#   powershell -ExecutionPolicy Bypass -File .\scripts\check_stage1.ps1
$ErrorActionPreference = "Continue"
Set-Location (Join-Path $PSScriptRoot "..")

$port = 8080
if (Test-Path .env) {
    $m = Select-String -Path .env -Pattern '^HTTP_PORT=(\d+)'
    if ($m) { $port = $m.Matches[0].Groups[1].Value }
}
$base = "http://localhost:$port"
$script:failed = 0

function Check([string]$Name, [scriptblock]$Test) {
    $err = ""
    try { $ok = & $Test } catch { $ok = $false; $err = $_.Exception.Message }
    if ($ok) { Write-Host "[OK]   $Name" -ForegroundColor Green }
    else { Write-Host "[FAIL] $Name $err" -ForegroundColor Red; $script:failed++ }
}

Check ".env существует, SECRET_KEY не заглушка" {
    (Test-Path .env) -and -not (Select-String -Path .env -Pattern '^SECRET_KEY=change-me' -Quiet)
}
Check "Docker Desktop запущен" { docker info *> $null; $LASTEXITCODE -eq 0 }
Check "compose.yaml валиден" { docker compose config -q *> $null; $LASTEXITCODE -eq 0 }
Check "Запущены db, redis, api, worker, nginx" {
    $running = @(docker compose ps --status running --services)
    $missing = @("db", "redis", "api", "worker", "nginx") | Where-Object { $running -notcontains $_ }
    if ($missing) { throw "не запущены: $($missing -join ', ')" }
    $true
}
Check "Конфиг nginx валиден (nginx -t)" { docker compose exec -T nginx nginx -t *> $null; $LASTEXITCODE -eq 0 }
Check "PostgreSQL не проброшен наружу" {
    # Без публикации compose печатает пустоту или ":0" - это не открытый порт
    $p = "$(docker compose port db 5432 2>$null)".Trim()
    if ($p -match ':([1-9]\d*)$') { throw "опубликован на $p" }
    $true
}
Check "GET /api/v1/health/live через nginx = 200" {
    (Invoke-WebRequest -UseBasicParsing "$base/api/v1/health/live" -TimeoutSec 5).StatusCode -eq 200
}
Check "GET /api/v1/health: db и redis доступны" {
    $r = Invoke-RestMethod "$base/api/v1/health" -TimeoutSec 10
    ($r.status -eq "ok") -and $r.db -and $r.redis
}
Check "Заголовки безопасности от nginx" {
    $h = (Invoke-WebRequest -UseBasicParsing "$base/api/v1/health/live" -TimeoutSec 5).Headers
    ($h["X-Content-Type-Options"] -eq "nosniff") -and ($h["X-Frame-Options"] -eq "DENY")
}
Check "Swagger /api/v1/docs открывается" {
    (Invoke-WebRequest -UseBasicParsing "$base/api/v1/docs" -TimeoutSec 5).StatusCode -eq 200
}
Check "Celery: api -> redis -> worker -> pong" {
    $out = docker compose exec -T api python -c "from app.tasks.system import ping; print(ping.delay().get(timeout=15))" 2>&1
    ("$($out | Select-Object -Last 1)").Trim() -eq "pong"
}
Check "pytest внутри контейнера api" {
    $out = docker compose exec -T api pytest 2>&1
    if ($LASTEXITCODE -ne 0) { $out | Write-Host }
    $LASTEXITCODE -eq 0
}

Write-Host ""
if ($script:failed -eq 0) {
    Write-Host "Этап 1 пройден: все проверки зелёные." -ForegroundColor Green
} else {
    Write-Host "Провалено проверок: $script:failed. Смотрите: docker compose logs api worker nginx" -ForegroundColor Red
    exit 1
}
