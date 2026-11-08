# Fix for Windows PowerShell 5.1: read API responses as UTF-8, no Count wrapper in JSON
Remove-TypeData System.Array -ErrorAction SilentlyContinue

function Invoke-RestMethod {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, Position = 0)][uri]$Uri,
        [string]$Method = 'GET',
        [System.Collections.IDictionary]$Headers,
        $Body,
        [string]$ContentType,
        [int]$TimeoutSec = 0
    )
    $p = @{ Uri = $Uri; Method = $Method; UseBasicParsing = $true }
    if ($Headers) { $p.Headers = $Headers }
    if ($null -ne $Body) { $p.Body = $Body }
    if ($ContentType) { $p.ContentType = $ContentType }
    if ($TimeoutSec) { $p.TimeoutSec = $TimeoutSec }
    $r = Microsoft.PowerShell.Utility\Invoke-WebRequest @p
    $text = [Text.Encoding]::UTF8.GetString($r.RawContentStream.ToArray())
    if ($text) { $text | ConvertFrom-Json }
}
