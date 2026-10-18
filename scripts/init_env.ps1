# Создаёт .env из .env.example со случайными SECRET_KEY и POSTGRES_PASSWORD.
# Запуск из корня проекта:
#   powershell -ExecutionPolicy Bypass -File .\scripts\init_env.ps1
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$example = Join-Path $root ".env.example"
$target = Join-Path $root ".env"

if (Test-Path $target) {
    Write-Host ".env уже существует, оставляю как есть." -ForegroundColor Yellow
    exit 0
}

function New-Secret([int]$Bytes) {
    $buf = New-Object byte[] $Bytes
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($buf)
    $rng.Dispose()
    return -join ($buf | ForEach-Object { $_.ToString("x2") })
}

$text = [IO.File]::ReadAllText($example)
$text = $text -replace "`r`n", "`n"
$text = $text -replace '(?m)^SECRET_KEY=.*$', ("SECRET_KEY=" + (New-Secret 32))
$text = $text -replace '(?m)^POSTGRES_PASSWORD=.*$', ("POSTGRES_PASSWORD=" + (New-Secret 16))

# UTF-8 без BOM и с LF, иначе docker compose может прочитать первую переменную криво
[IO.File]::WriteAllText($target, $text, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "Создан .env со случайными SECRET_KEY и POSTGRES_PASSWORD." -ForegroundColor Green
