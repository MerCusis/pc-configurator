# Резервная копия базы. Хранятся 7 последних копий в папке backups.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$service = 'db'
$keep = 7
$dir = Join-Path $PSScriptRoot 'backups'
New-Item -ItemType Directory -Force $dir | Out-Null
$file = Join-Path $dir ("pc-{0:yyyy-MM-dd_HH-mm}.dump" -f (Get-Date))

# Дамп делается внутри контейнера, затем копируется на диск.
# Перенаправление через > в PowerShell портит двоичный файл, поэтому так.
docker compose exec -T $service sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/backup.dump'
if ($LASTEXITCODE -ne 0) { throw 'pg_dump завершился с ошибкой' }

docker compose cp "${service}:/tmp/backup.dump" $file
if ($LASTEXITCODE -ne 0) { throw 'Не удалось скопировать дамп из контейнера' }
docker compose exec -T $service rm -f /tmp/backup.dump

Get-ChildItem $dir -Filter *.dump | Sort-Object LastWriteTime -Descending |
  Select-Object -Skip $keep | Remove-Item

Write-Host "Готово: $file ($([math]::Round((Get-Item $file).Length / 1MB, 1)) МБ)"