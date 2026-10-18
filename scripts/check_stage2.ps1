# Проверка этапа 2. Запуск из корня проекта после миграций, seed и create_admin:
#   powershell -ExecutionPolicy Bypass -File .\scripts\check_stage2.ps1
$ErrorActionPreference = "Continue"
Set-Location (Join-Path $PSScriptRoot "..")
$script:failed = 0

function Check([string]$Name, [scriptblock]$Test) {
    $err = ""
    try { $ok = & $Test } catch { $ok = $false; $err = $_.Exception.Message }
    if ($ok) { Write-Host "[OK]   $Name" -ForegroundColor Green }
    else { Write-Host "[FAIL] $Name $err" -ForegroundColor Red; $script:failed++ }
}

function Api-Json([string[]]$CmdArgs) {
    $out = docker compose exec -T api @CmdArgs 2>$null
    if ($LASTEXITCODE -ne 0) { throw "команда завершилась с кодом $LASTEXITCODE" }
    ($out | Select-Object -Last 1) | ConvertFrom-Json
}

Check "Запущены db, redis, api, worker" {
    $running = @(docker compose ps --status running --services)
    $missing = @("db", "redis", "api", "worker") | Where-Object { $running -notcontains $_ }
    if ($missing) { throw "не запущены: $($missing -join ', ')" }
    $true
}

$status = $null
Check "Миграции применены до head" {
    $script:status = Api-Json @("python", "-m", "app.scripts.db_status")
    if (-not $script:status.up_to_date) { throw "текущая $($script:status.revision), head $($script:status.head). Выполните alembic upgrade head" }
    $true
}
Check "Модели совпадают с миграциями (alembic check)" {
    docker compose exec -T api alembic check *> $null; $LASTEXITCODE -eq 0
}
Check "Seed идемпотентен: повторный запуск ничего не меняет" {
    $null = Api-Json @("python", "-m", "app.scripts.seed")
    $s = Api-Json @("python", "-m", "app.scripts.seed")
    $sum = ($s.PSObject.Properties | Measure-Object -Property Value -Sum).Sum
    if ($sum -ne 0) { throw "повторный seed изменил данные: $($s | ConvertTo-Json -Compress)" }
    $true
}
Check "Каталог загружен: 8 категорий, 8 правил, детали с ценами" {
    $d = Api-Json @("python", "-m", "app.scripts.db_status")
    if ($d.categories -ne 8 -or $d.rules -lt 8 -or $d.parts -lt 1 -or $d.price_history -lt $d.parts) {
        throw ($d | ConvertTo-Json -Compress)
    }
    $true
}
Check "Создан хотя бы один администратор" {
    $d = Api-Json @("python", "-m", "app.scripts.db_status")
    if ($d.admins -lt 1) { throw "выполните: docker compose exec api python -m app.scripts.create_admin --username admin" }
    $true
}
Check "pytest внутри api, включая тесты на PostgreSQL" {
    $out = docker compose exec -T -e REQUIRE_DB=1 api pytest 2>&1
    $code = $LASTEXITCODE
    $out | Select-Object -Last 3 | Write-Host
    if ($code -ne 0) { $out | Write-Host }
    $code -eq 0
}

Write-Host ""
if ($script:failed -eq 0) {
    Write-Host "Этап 2 пройден: все проверки зелёные." -ForegroundColor Green
} else {
    Write-Host "Провалено проверок: $script:failed. Смотрите: docker compose logs api db" -ForegroundColor Red
    exit 1
}
