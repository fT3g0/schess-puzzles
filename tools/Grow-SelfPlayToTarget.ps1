param(
    [int]$TargetVisible = 500,
    [int]$MaxBatches = 200,
    [int]$SelfPlayGames = 20,
    [int]$SelectorDepth = 10,
    [int]$MultiPv = 6,
    [int]$ConfirmDepth = 20,
    [int]$ConfirmMultiPv = 6,
    [int]$LineMaxPlies = 5,
    [int]$SelfPlayDepth = 1,
    [int]$SelfPlayMaxPlies = 120,
    [int]$TemperatureCp = 250,
    [double]$BlunderChance = 0.20,
    [int]$ResignCp = 700,
    [int]$ResignMoves = 5,
    [int]$SeedBase = 2000
)

$ErrorActionPreference = "Stop"

function Invoke-Python {
    param([string[]]$CommandArgs)
    Write-Host ""
    Write-Host "> python $($CommandArgs -join ' ')"
    & python @CommandArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE"
    }
}

function Get-NextSelfPlayBatch {
    $max = 0
    Get-ChildItem -Path "data\puzzles" -Filter "selfplay_batch*_report.jsonl" -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.Name -match 'selfplay_batch(\d+)_report\.jsonl') {
            $max = [Math]::Max($max, [int]$Matches[1])
        }
    }
    return ($max + 1)
}

function Get-VisibleCount {
    $path = "data\puzzles\all_report.jsonl"
    if (-not (Test-Path $path)) {
        return 0
    }
    $hidden = @{
        "standard-like" = $true
        "trivial-recapture" = $true
        "trivial-capture" = $true
        "check-evasion" = $true
    }
    $count = 0
    foreach ($line in Get-Content -Path $path) {
        if (-not $line.Trim()) {
            continue
        }
        $record = $line | ConvertFrom-Json
        $isHidden = $false
        foreach ($flag in @($record.flags)) {
            if ($hidden.ContainsKey([string]$flag)) {
                $isHidden = $true
                break
            }
        }
        if (-not $isHidden) {
            $count += 1
        }
    }
    return $count
}

function Update-CombinedArtifacts {
    $reports = @()
    if (Test-Path "data\puzzles\all_report.jsonl") {
        $reports += "data\puzzles\all_report.jsonl"
    }
    if (Test-Path "data\puzzles\chesscom_all_report.jsonl") {
        $reports += "data\puzzles\chesscom_all_report.jsonl"
    }
    $reports += Get-ChildItem -Path "data\puzzles" -Filter "selfplay_batch*_report.jsonl" | Sort-Object Name | ForEach-Object { $_.FullName }

    $tmp = "data\puzzles\all_report.next.jsonl"
    Invoke-Python (@("-m", "schess_puzzles.cli", "combine-reports") + $reports + @("--output", $tmp))
    Move-Item -Force -Path $tmp -Destination "data\puzzles\all_report.jsonl"
    Invoke-Python @("-m", "schess_puzzles.cli", "review-html", "data\puzzles\all_report.jsonl", "data\puzzles\all_review.html")
    Invoke-Python @("-m", "schess_puzzles.cli", "export-web", "data\puzzles\all_report.jsonl", "web\public\puzzles.json")

    powershell -ExecutionPolicy Bypass -File ".\tools\Publish-WebToDocs.ps1"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not publish web/ to docs/"
    }
}

Update-CombinedArtifacts
$visible = Get-VisibleCount
Write-Host "Visible puzzles before run: $visible / $TargetVisible"

$batchesRun = 0
while ($visible -lt $TargetVisible -and $batchesRun -lt $MaxBatches) {
    $batch = Get-NextSelfPlayBatch
    $batchName = "selfplay_batch{0:D2}" -f $batch
    $rawDir = "data\raw\$batchName"
    $jsonl = "data\puzzles\$batchName.jsonl"
    $report = "data\puzzles\${batchName}_report.jsonl"
    $html = "data\puzzles\${batchName}_review.html"
    $seed = $SeedBase + $batch

    Write-Host ""
    Write-Host "=== Generating $batchName (seed $seed) ==="

    $existingGames = 0
    if (Test-Path $rawDir) {
        $existingGames = @(Get-ChildItem -Path $rawDir -Filter "*.pgn" -ErrorAction SilentlyContinue).Count
    }
    if ($existingGames -ge $SelfPlayGames) {
        Write-Host "Reusing existing $rawDir with $existingGames PGN(s)."
    } else {
        Invoke-Python @(
            "-m", "schess_puzzles.cli", "selfplay",
            "--games", "$SelfPlayGames",
            "--output-dir", $rawDir,
            "--prefix", $batchName,
            "--depth", "$SelfPlayDepth",
            "--multipv", "$MultiPv",
            "--max-plies", "$SelfPlayMaxPlies",
            "--temperature-cp", "$TemperatureCp",
            "--blunder-chance", "$BlunderChance",
            "--resign-cp", "$ResignCp",
            "--resign-moves", "$ResignMoves",
            "--seed", "$seed"
        )
    }

    if (Test-Path $report) {
        Write-Host "Reusing existing $report."
    } else {
        Invoke-Python @(
            "-m", "schess_puzzles.cli", "select-batch",
            "--glob", "$rawDir/*.pgn",
            "--limit", "$SelfPlayGames",
            "--depth", "$SelectorDepth",
            "--multipv", "$MultiPv",
            "--confirm-depth", "$ConfirmDepth",
            "--confirm-multipv", "$ConfirmMultiPv",
            "--extend-critical",
            "--max-plies", "$LineMaxPlies",
            "--output-jsonl", $jsonl,
            "--report-jsonl", $report
        )
        Invoke-Python @("-m", "schess_puzzles.cli", "refresh-report-flags", $report)
        Invoke-Python @("-m", "schess_puzzles.cli", "review-html", $report, $html)
    }

    Update-CombinedArtifacts
    $visible = Get-VisibleCount
    $batchesRun += 1
    Write-Host "Visible puzzles after ${batchName}: $visible / $TargetVisible"
}

Write-Host ""
Write-Host "Growth run finished. visible=$visible target=$TargetVisible batches_run=$batchesRun"
Write-Host "Review: data\puzzles\all_review.html"
Write-Host "Publish files: docs\"



