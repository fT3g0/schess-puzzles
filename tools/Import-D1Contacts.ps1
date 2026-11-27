param(
    [int]$PageSize = 100
)

$ErrorActionPreference = 'Stop'
if ($PageSize -lt 1 -or $PageSize -gt 1000) { throw 'PageSize must be between 1 and 1000.' }
$root = Split-Path -Parent $PSScriptRoot
$workerRoot = Join-Path $root 'cloudflare\suggestions-worker'
$storageRoot = Join-Path $root 'data\contacts'
$npx = 'D:\Program Files\nodejs\npx.cmd'
if (-not (Test-Path -LiteralPath $npx)) { throw "npx.cmd not found: $npx" }
New-Item -ItemType Directory -Path $storageRoot -Force | Out-Null
$logPath = Join-Path $storageRoot 'import.log'
$saved = 0
$cursor = 0
try {
    do {
        $query = "SELECT id, created_at, name, email, message, page_url FROM contact_messages WHERE id > $cursor ORDER BY id ASC LIMIT $PageSize"
        Push-Location $workerRoot
        try {
            $raw = & $npx wrangler d1 execute schess-puzzle-suggestions --remote --command $query --json 2>&1 | Out-String
            if ($LASTEXITCODE -ne 0) { throw "Wrangler query failed: $raw" }
        } finally { Pop-Location }
        try { $payload = $raw | ConvertFrom-Json } catch { throw 'Wrangler did not return valid JSON.' }
        $items = if ($payload -is [array]) { $payload } elseif ($null -ne $payload.result) { @($payload.result) } else { @($payload) }
        $rows = @($items | ForEach-Object { if ($null -ne $_.results) { $_.results } })
        foreach ($row in $rows) {
            $id = [int64]$row.id
            if ($id -le $cursor) { throw 'D1 returned an invalid or out-of-order message ID.' }
            $cursor = $id
            $path = Join-Path $storageRoot ("contact_{0}.json" -f $id)
            if (-not (Test-Path -LiteralPath $path)) {
                $entry = [ordered]@{ id = $id; created_at = $row.created_at; name = $row.name; email = $row.email; message = $row.message; page_url = $row.page_url }
                $json = $entry | ConvertTo-Json -Depth 4
                $stream = [System.IO.File]::Open($path, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
                try { $writer = New-Object System.IO.StreamWriter($stream, (New-Object System.Text.UTF8Encoding $false)); try { $writer.Write($json) } finally { $writer.Dispose() } } finally { $stream.Dispose() }
                $saved++
            }
        }
    } while ($rows.Count -eq $PageSize)
    $status = "$(Get-Date -Format o) OK new=$saved last_id=$cursor"
    Add-Content -LiteralPath $logPath -Value $status -Encoding UTF8
    Write-Host $status
} catch {
    $status = "$(Get-Date -Format o) ERROR $($_.Exception.Message)"
    Add-Content -LiteralPath $logPath -Value $status -Encoding UTF8
    Write-Error $status
    exit 1
}
