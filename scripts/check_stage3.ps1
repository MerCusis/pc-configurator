# Проверка этапа 3. Запуск из корня проекта:
#   powershell -ExecutionPolicy Bypass -File .\scripts\check_stage3.ps1
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
    ($out | Select-Object -Last 1) | ConvertFrom-Json
}

$base = @("amd-ryzen5-7600", "msi-b650-gaming-plus-wifi", "kingston-fury-ddr5-32-6000", "palit-rtx4060-dual",
          "samsung-990pro-1tb", "deepcool-pk650d", "bequiet-pure-base-500", "deepcool-ak400")

Check "Запущены db, redis, api, worker" {
    $running = @(docker compose ps --status running --services)
    $missing = @("db", "redis", "api", "worker") | Where-Object { $running -notcontains $_ }
    if ($missing) { throw "не запущены: $($missing -join ', ')" }
    $true
}
Check "Миграции применены до head" {
    $s = Api-Json @("python", "-m", "app.scripts.db_status")
    if (-not $s.up_to_date) { throw "текущая $($s.revision), head $($s.head). Выполните alembic upgrade head" }
    $true
}
Check "Демо-сборка из seed полная и совместимая" {
    $r = Api-Json (@("python", "-m", "app.scripts.check_build") + $base)
    if (-not $r.is_complete -or $r.error_count -ne 0) { throw ($r | ConvertTo-Json -Compress -Depth 6) }
    Write-Host "       пик $($r.power.peak_w) Вт, рекомендуемый БП $($r.power.suggested_psu_w) Вт, цена $($r.total_price)"
    $true
}
Check "Плата AM4 с CPU AM5 и DDR5 даёт socket_mismatch и ram_type_motherboard" {
    $bad = $base | ForEach-Object { if ($_ -eq "msi-b650-gaming-plus-wifi") { "gigabyte-b550m-ds3h" } else { $_ } }
    $r = Api-Json (@("python", "-m", "app.scripts.check_build") + $bad)
    $codes = @($r.issues | Where-Object { $_.severity -eq "error" } | ForEach-Object { $_.code })
    if ($r.is_compatible -or $codes -notcontains "socket_mismatch" -or $codes -notcontains "ram_type_motherboard") {
        throw "коды ошибок: $($codes -join ', ')"
    }
    $true
}
Check "Неизвестная деталь отклоняется" {
    $r = Api-Json @("python", "-m", "app.scripts.check_build", "no-such-part")
    $r.error -eq "unknown_parts"
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
    Write-Host "Этап 3 пройден: все проверки зелёные." -ForegroundColor Green
} else {
    Write-Host "Провалено проверок: $script:failed. Смотрите: docker compose logs api db" -ForegroundColor Red
    exit 1
}
