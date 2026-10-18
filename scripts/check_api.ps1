# Проверка API этапа 4. Запуск: powershell -ExecutionPolicy Bypass -File scripts\check_api.ps1
param([string]$BaseUrl = "http://localhost:8000")
$ErrorActionPreference = "Stop"
$api = "$BaseUrl/api/v1"
$script:fail = 0
$samples = [ordered]@{}

function Step([string]$name, [scriptblock]$block) {
    try {
        $r = & $block
        Write-Host "[OK]   $name" -ForegroundColor Green
        $samples[$name] = $r
        return $r
    } catch {
        Write-Host "[FAIL] $name : $($_.Exception.Message)" -ForegroundColor Red
        $script:fail++
        return $null
    }
}
function Prop($obj, [string]$pattern) {
    if (-not $obj) { return $null }
    $p = $obj.PSObject.Properties | Where-Object { $_.Name -match $pattern } | Select-Object -First 1
    if ($p) { return $p.Value } else { return $null }
}
function Body($o) { return [Text.Encoding]::UTF8.GetBytes(($o | ConvertTo-Json -Depth 6)) }
$ct = "application/json; charset=utf-8"

$spec = Step "openapi.json" { Invoke-RestMethod "$BaseUrl/openapi.json" }
if ($spec -and -not $spec.components.securitySchemes) {
    Write-Host "[FAIL] в openapi.json нет securitySchemes: openapi_patch не подключён" -ForegroundColor Red; $script:fail++
}
Step "health/live" { Invoke-RestMethod "$api/health/live" } | Out-Null
Step "health" { Invoke-RestMethod "$api/health" } | Out-Null

$sess = Step "POST session" { Invoke-RestMethod -Method Post "$api/session" }
$token = Prop $sess 'token'
if (-not $token) { Write-Host "[FAIL] в ответе /session нет поля с token" -ForegroundColor Red; $script:fail++ }
$h = @{ Authorization = "Bearer $token" }
Step "GET session" { Invoke-RestMethod "$api/session" -Headers $h } | Out-Null

try {
    Invoke-WebRequest "$api/builds" -UseBasicParsing | Out-Null
    Write-Host "[FAIL] /builds без токена должен отвечать 401" -ForegroundColor Red; $script:fail++
} catch {
    $code = [int]$_.Exception.Response.StatusCode
    if ($code -eq 401) { Write-Host "[OK]   /builds без токена -> 401" -ForegroundColor Green }
    else { Write-Host "[FAIL] /builds без токена -> $code, ожидали 401" -ForegroundColor Red; $script:fail++ }
}

Step "categories" { Invoke-RestMethod "$api/categories" } | Out-Null
Step "manufacturers" { Invoke-RestMethod "$api/manufacturers" } | Out-Null
$parts = Step "parts?limit=5" { Invoke-RestMethod "$api/parts?limit=5&has_price=true" }
$list = if ($parts -and $parts.items) { @($parts.items) } else { @($parts) }
$partId = if ($list.Count -gt 0) { $list[0].id } else { $null }
if (-not $partId) { Write-Host "[FAIL] каталог пуст: выполните импорт или seed" -ForegroundColor Red; $script:fail++ }
else {
    Step "parts/{id}" { Invoke-RestMethod "$api/parts/$partId" } | Out-Null
    $items = @(@{ part_id = [int64]$partId; quantity = 1 })
    Step "compatibility/check" { Invoke-RestMethod -Method Post "$api/compatibility/check" -ContentType $ct -Body (Body @{ items = $items }) } | Out-Null
    $build = Step "POST builds" { Invoke-RestMethod -Method Post "$api/builds" -Headers $h -ContentType $ct -Body (Body @{ name = "Проверка API"; items = $items }) }
    $bid = Prop $build '^id$'
    if ($bid) {
        Step "GET builds" { Invoke-RestMethod "$api/builds" -Headers $h } | Out-Null
        Step "PUT builds/{id}" { Invoke-RestMethod -Method Put "$api/builds/$bid" -Headers $h -ContentType $ct -Body (Body @{ name = "Проверка API 2"; items = $items }) } | Out-Null
        $share = Step "POST share" { Invoke-RestMethod -Method Post "$api/builds/$bid/share" -Headers $h }
        $slug = Prop $share 'slug'
        if ($slug) { Step "GET shared/{slug}" { Invoke-RestMethod "$api/shared/$slug" } | Out-Null }
        else { Write-Host "[FAIL] в ответе share нет slug" -ForegroundColor Red; $script:fail++ }
        Step "DELETE share" { Invoke-RestMethod -Method Delete "$api/builds/$bid/share" -Headers $h } | Out-Null
        Step "DELETE build" { Invoke-RestMethod -Method Delete "$api/builds/$bid" -Headers $h } | Out-Null
    } else { Write-Host "[FAIL] в ответе POST builds нет id" -ForegroundColor Red; $script:fail++ }
}

$samples.Remove("openapi.json")
$json = $samples | ConvertTo-Json -Depth 8
[IO.File]::WriteAllText((Join-Path (Get-Location) "samples.json"), $json, (New-Object Text.UTF8Encoding $false))
try { Set-Clipboard -Value $json } catch {}
Write-Host ""
if ($script:fail -eq 0) { Write-Host "Все проверки пройдены. samples.json сохранён и скопирован в буфер." -ForegroundColor Green; exit 0 }
else { Write-Host "Ошибок: $($script:fail). samples.json всё равно сохранён." -ForegroundColor Red; exit 1 }
