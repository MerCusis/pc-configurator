# Проверка этапа 4. Запуск из корня проекта:
#   powershell -ExecutionPolicy Bypass -File .\scripts\check_stage4.ps1
# Ключ -Import дополнительно загружает каталог docyx/pc-part-dataset (нужен интернет, несколько минут).
param([switch]$Import)
$ErrorActionPreference = "Continue"
Set-Location (Join-Path $PSScriptRoot "..")
$script:failed = 0

function Check([string]$Name, [scriptblock]$Test) {
    $err = ""
    try { $ok = & $Test } catch { $ok = $false; $err = $_.Exception.Message }
    if ($ok) { Write-Host "[OK]   $Name" -ForegroundColor Green }
    else { Write-Host "[FAIL] $Name $err" -ForegroundColor Red; $script:failed++ }
}

$port = if ($env:HTTP_PORT) { $env:HTTP_PORT } else { "8080" }
$api = "http://127.0.0.1:$port/api/v1"

function Call([string]$Method, [string]$Path, $Body = $null, $Headers = @{}) {
    $p = @{ Method = $Method; Uri = "$api$Path"; Headers = $Headers; ContentType = "application/json; charset=utf-8" }
    if ($null -ne $Body) { $p.Body = [Text.Encoding]::UTF8.GetBytes(($Body | ConvertTo-Json -Depth 6 -Compress)) }
    Invoke-RestMethod @p
}

$base = @("amd-ryzen5-7600", "msi-b650-gaming-plus-wifi", "kingston-fury-ddr5-32-6000", "palit-rtx4060-dual",
          "samsung-990pro-1tb", "deepcool-pk650d", "bequiet-pure-base-500", "deepcool-ak400")

Check "Запущены db, redis, api, worker, nginx" {
    $running = @(docker compose ps --status running --services)
    $missing = @("db", "redis", "api", "worker", "nginx") | Where-Object { $running -notcontains $_ }
    if ($missing) { throw "не запущены: $($missing -join ', ')" }
    $true
}
Check "Каталог отвечает через nginx" {
    $cats = @(Call GET "/categories")
    $parts = Call GET "/parts?limit=5"
    Write-Host "       категорий $($cats.Count), деталей в каталоге $($parts.total)"
    $cats.Count -ge 8 -and $parts.total -gt 0
}
$script:h = $null
Check "Выдача anon_token, лимит 15 сборок" {
    $s = Call POST "/session"
    $script:h = @{ Authorization = "Bearer $($s.anon_token)" }
    $s.builds_limit -eq 15 -and $s.anon_token.Length -ge 40
}
Check "Проверка совместимости через API" {
    $cpu = Call GET "/parts?category=cpu&socket=AM5&has_price=true&limit=1"
    $mb = Call GET "/parts?category=motherboard&socket=AM5&has_price=true&limit=1"
    if (-not $cpu.items -or -not $mb.items) { throw "в каталоге нет CPU или платы AM5 с ценой" }
    $r = Call POST "/compatibility/check" @{ items = @(@{ part_id = $cpu.items[0].id }, @{ part_id = $mb.items[0].id }) }
    $codes = @($r.issues | Where-Object { $_.severity -eq "error" } | ForEach-Object { $_.code })
    if ($codes -contains "socket_mismatch") { throw "ложный socket_mismatch" }
    $true
}
Check "Сборка: создание, публичная ссылка, удаление" {
    $cpu = (Call GET "/parts?category=cpu&has_price=true&limit=1").items[0]
    $b = Call POST "/builds" @{ name = "check_stage4"; items = @(@{ part_id = $cpu.id }) } $script:h
    $sh = Call POST "/builds/$($b.id)/share" $null $script:h
    $slug = if ($sh.share_slug) { $sh.share_slug } else { $sh.slug }
    $pub = Call GET "/shared/$slug"
    Call DELETE "/builds/$($b.id)" $null $script:h | Out-Null
    $pub.name -eq "check_stage4"
}
Check "Чужой токен не видит сборку" {
    try { Call GET "/builds" $null @{ Authorization = "Bearer invalid-token-000000000000000000000000000000" } | Out-Null; $false }
    catch { $_.Exception.Response.StatusCode.value__ -eq 401 }
}
if ($Import) {
    Check "Импорт docyx/pc-part-dataset" {
        docker compose exec -T api python -m app.scripts.import_docyx --skip-unpriced 2>&1 | Select-Object -Last 12 | Write-Host
        $LASTEXITCODE -eq 0
    }
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
    Write-Host "Этап 4 пройден: все проверки зелёные." -ForegroundColor Green
} else {
    Write-Host "Провалено проверок: $script:failed. Смотрите: docker compose logs api nginx db" -ForegroundColor Red
    exit 1
}
