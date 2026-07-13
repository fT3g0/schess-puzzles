param(
    [int]$Limit = 20,
    [switch]$Analyze,
    [int]$Depth = 22
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$workerRoot = Join-Path $repoRoot "cloudflare\suggestions-worker"
$storageRoot = Join-Path $repoRoot "data\suggestions"
$npx = "D:\Program Files\nodejs\npx.cmd"

if (-not (Test-Path -LiteralPath $npx)) { throw "npx.cmd not found at $npx" }
if (-not (Test-Path -LiteralPath $workerRoot)) { throw "Worker directory not found: $workerRoot" }
New-Item -ItemType Directory -Path $storageRoot -Force | Out-Null

$query = "SELECT id, created_at, status, fen, notes, page_url FROM suggestions WHERE status = 'new' ORDER BY created_at ASC LIMIT $Limit"
Push-Location $workerRoot
try {
    $raw = & $npx wrangler d1 execute schess-puzzle-suggestions --remote --command $query --json 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) { throw "Wrangler query failed:`n$raw" }
} finally {
    Pop-Location
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$snapshotPath = Join-Path $storageRoot "d1_snapshot_$timestamp.json"
[System.IO.File]::WriteAllText($snapshotPath, $raw, (New-Object System.Text.UTF8Encoding $false))
try { $payload = $raw | ConvertFrom-Json } catch { throw "Wrangler did not return valid JSON. Raw response saved to $snapshotPath" }

$rows = @()
if ($payload.result) {
    foreach ($result in @($payload.result)) {
        if ($result.results) { $rows += @($result.results) }
    }
} elseif ($payload.results) {
    $rows = @($payload.results)
}

$indexPath = Join-Path $storageRoot "imported_ids.json"
$known = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
if (Test-Path -LiteralPath $indexPath) {
    foreach ($id in @((Get-Content -LiteralPath $indexPath -Raw | ConvertFrom-Json))) { [void]$known.Add([string]$id) }
}

$newRows = @($rows | Where-Object { $_.id -and $known.Add([string]$_.id) })
foreach ($row in $newRows) {
    $rowPath = Join-Path $storageRoot ("d1_{0}.json" -f $row.id)
    $entry = [ordered]@{
        d1_id = [int]$row.id
        created_at = [string]$row.created_at
        status = [string]$row.status
        fen = [string]$row.fen
        notes = [string]$row.notes
        page_url = [string]$row.page_url
        local_status = "imported"
        analysis_status = "pending"
    }
    [System.IO.File]::WriteAllText($rowPath, ($entry | ConvertTo-Json -Depth 4), (New-Object System.Text.UTF8Encoding $false))
}

$known | Sort-Object | ConvertTo-Json | Set-Content -LiteralPath $indexPath -Encoding utf8
$inboxPath = Join-Path $storageRoot "pending.jsonl"
$allEntries = Get-ChildItem -LiteralPath $storageRoot -Filter "d1_*.json" | Where-Object { $_.Name -match "^d1_\\d+\\.json$" } | Sort-Object Name | ForEach-Object { Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json }
$allEntries | ForEach-Object { $_ | ConvertTo-Json -Compress } | Set-Content -LiteralPath $inboxPath -Encoding utf8

Write-Host "D1 suggestions: fetched=$($rows.Count) newly_saved=$($newRows.Count) inbox=$inboxPath"
foreach ($row in $newRows) {
    Write-Host ("  id={0} created={1} notes={2}" -f $row.id, $row.created_at, ([string]$row.notes).Replace("`r", " ").Replace("`n", " "))
}

if (-not $Analyze) {
    if ($newRows.Count) { Write-Host "Run with -Analyze to create high-depth reports without changing the remote D1 status." }
    exit 0
}

$toAnalyze = @($allEntries | Where-Object { $_.analysis_status -ne "completed" })
if (-not $toAnalyze.Count) {
    Write-Host "No locally pending suggestions need an engine pre-check."
    exit 0
}

Push-Location $repoRoot
try {
    foreach ($entry in $toAnalyze) {
        $id = [int]$entry.d1_id
        $base = "data\puzzles\suggested_d1_$id"
        Write-Host "Analyzing D1 suggestion $id..."
        & python -m schess_puzzles.cli suggest-fen ([string]$entry.fen) --source "user_suggestion_d1_$id" --depth $Depth --multipv 8 --extend-depth 12 --max-plies 13 --extension-beam-width 2 --include-standard-positions --output-jsonl "$base.jsonl" --report-jsonl "${base}_report.jsonl"
        $entry | Add-Member -NotePropertyName analysis_status -NotePropertyValue "pending" -Force
        $entry | Add-Member -NotePropertyName analysis_report -NotePropertyValue "${base}_report.jsonl" -Force
        Add-Member -InputObject $entry -NotePropertyName analysis_status -NotePropertyValue (if ($LASTEXITCODE -eq 0) { "completed" } else { "failed" }) -Force
        if ($entry.analysis_status -eq "failed") { Write-Warning "Suggestion $id analysis failed; its local inbox entry was retained." }
        $entryPath = Join-Path $storageRoot ("d1_{0}.json" -f $id)
        [System.IO.File]::WriteAllText($entryPath, ($entry | ConvertTo-Json -Depth 4), (New-Object System.Text.UTF8Encoding $false))
    }
} finally {
    Pop-Location
}

$allEntries = Get-ChildItem -LiteralPath $storageRoot -Filter "d1_*.json" | Where-Object { $_.Name -match "^d1_\\d+\\.json$" } | Sort-Object Name | ForEach-Object { Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json }
$allEntries | ForEach-Object { $_ | ConvertTo-Json -Compress } | Set-Content -LiteralPath $inboxPath -Encoding utf8