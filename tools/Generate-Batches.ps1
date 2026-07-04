param(
    [int]$ChessComStartBatch = 50,
    [int]$ChessComBatches = 0,
    [int]$ChessComBatchSize = 20,
    [int]$SelfPlayStartBatch = 8,
    [int]$SelfPlayBatches = 0,
    [int]$SelfPlayGames = 20,
    [int]$SelectorDepth = 10,
    [int]$MultiPv = 6,
    [int]$ConfirmDepth = 20,
    [int]$ConfirmMultiPv = 3,
    [int]$ConfirmFastDepth = 17,
    [int]$LineMaxPlies = 7,
    [int]$ExtensionBeamWidth = 2,
    [int]$SelfPlayDepth = 1,
    [int]$SelfPlayMaxPlies = 120,
    [int]$TemperatureCp = 250,
    [double]$BlunderChance = 0.20,
    [int]$ResignCp = 700,
    [int]$ResignMoves = 5,
    [int]$SeedBase = 2000,
    [switch]$Combine
)

$ErrorActionPreference = "Stop"

function Invoke-Step {
    param([string[]]$CommandArgs)
    Write-Host ""
    Write-Host "> python $($CommandArgs -join ' ')"
    & python @CommandArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE"
    }
}

for ($offset = 0; $offset -lt $ChessComBatches; $offset++) {
    $batch = $ChessComStartBatch + $offset
    $batchName = "chesscom_batch{0:D2}" -f $batch
    $startIndex = ($batch - 1) * $ChessComBatchSize
    $jsonl = "data\puzzles\$batchName.jsonl"
    $report = "data\puzzles\${batchName}_report.jsonl"
    $html = "data\puzzles\${batchName}_review.html"

    Invoke-Step @(
        "-m", "schess_puzzles.cli", "select-batch",
        "--start-index", "$startIndex",
        "--limit", "$ChessComBatchSize",
        "--depth", "$SelectorDepth",
        "--multipv", "$MultiPv",
        "--confirm-depth", "$ConfirmDepth",
        "--confirm-multipv", "$ConfirmMultiPv",
        "--confirm-fast-depth", "$ConfirmFastDepth",
        "--extend-critical",
        "--max-plies", "$LineMaxPlies",
        "--extension-beam-width", "$ExtensionBeamWidth",
        "--output-jsonl", $jsonl,
        "--report-jsonl", $report
    )
    Invoke-Step @("-m", "schess_puzzles.cli", "refresh-report-flags", $report)
    Invoke-Step @("-m", "schess_puzzles.cli", "review-html", $report, $html)
}

for ($offset = 0; $offset -lt $SelfPlayBatches; $offset++) {
    $batch = $SelfPlayStartBatch + $offset
    $batchName = "selfplay_batch{0:D2}" -f $batch
    $rawDir = "data\raw\$batchName"
    $jsonl = "data\puzzles\$batchName.jsonl"
    $report = "data\puzzles\${batchName}_report.jsonl"
    $html = "data\puzzles\${batchName}_review.html"
    $seed = $SeedBase + $batch

    Invoke-Step @(
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
    Invoke-Step @(
        "-m", "schess_puzzles.cli", "select-batch",
        "--glob", "$rawDir/*.pgn",
        "--limit", "$SelfPlayGames",
        "--depth", "$SelectorDepth",
        "--multipv", "$MultiPv",
        "--confirm-depth", "$ConfirmDepth",
        "--confirm-multipv", "$ConfirmMultiPv",
        "--confirm-fast-depth", "$ConfirmFastDepth",
        "--extend-critical",
        "--max-plies", "$LineMaxPlies",
        "--extension-beam-width", "$ExtensionBeamWidth",
        "--output-jsonl", $jsonl,
        "--report-jsonl", $report
    )
    Invoke-Step @("-m", "schess_puzzles.cli", "refresh-report-flags", $report)
    Invoke-Step @("-m", "schess_puzzles.cli", "review-html", $report, $html)
}

if ($Combine) {
    Invoke-Step @(
        "-m", "schess_puzzles.cli", "combine-reports",
        "--output", "data\puzzles\chesscom_all_report.jsonl"
    )
    Invoke-Step @(
        "-m", "schess_puzzles.cli", "review-html",
        "data\puzzles\chesscom_all_report.jsonl",
        "data\puzzles\chesscom_all_review.html"
    )
}
