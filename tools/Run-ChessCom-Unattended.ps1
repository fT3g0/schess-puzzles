param(
    [string]$CookieFile = "cookies_env.txt",
    [int]$ArchiveStartPage = 50,
    [int]$ArchivePages = 50,
    [int]$ArchiveChunkPages = 5,
    [double]$DownloadDelay = 1.0,
    [int]$BatchSize = 20,
    [int]$MaxBatches = 9999,
    [string]$ProcessedManifest = "data\puzzles\chesscom_processed_raw.txt",
    [switch]$CombineAfterEachChunk,
    [switch]$NoFinalCombine
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

function Get-RawChessComCount {
    return (Get-ChildItem data\raw -Filter "chesscom_*.pgn4.txt" -File).Count
}

function Get-NextChessComBatch {
    $reports = Get-ChildItem data\puzzles -Filter "chesscom_batch*_report.jsonl" -File -ErrorAction SilentlyContinue
    $max = 1
    foreach ($report in $reports) {
        if ($report.Name -match "^chesscom_batch(\d+)_report\.jsonl$") {
            $number = [int]$Matches[1]
            if ($number -gt $max) {
                $max = $number
            }
        }
    }
    return $max + 1
}

function Get-NormalizedPath {
    param([System.IO.FileInfo]$Path)
    return $Path.FullName.ToLowerInvariant()
}

function Initialize-ProcessedManifest {
    if (Test-Path -LiteralPath $ProcessedManifest) {
        return
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ProcessedManifest) | Out-Null
    Get-ChildItem data\raw -Filter "chesscom_*.pgn4.txt" -File |
        ForEach-Object { Get-NormalizedPath $_ } |
        Set-Content -LiteralPath $ProcessedManifest -Encoding UTF8
    Write-Host "Initialized processed manifest with current raw files: $ProcessedManifest"
}

function Get-ProcessedSet {
    $set = [System.Collections.Generic.HashSet[string]]::new()
    if (Test-Path -LiteralPath $ProcessedManifest) {
        foreach ($line in Get-Content -LiteralPath $ProcessedManifest) {
            if ($line.Trim()) {
                [void]$set.Add($line.Trim().ToLowerInvariant())
            }
        }
    }
    return $set
}

function Add-ProcessedFiles {
    param([System.IO.FileInfo[]]$Files)
    foreach ($file in $Files) {
        Add-Content -LiteralPath $ProcessedManifest -Encoding UTF8 -Value (Get-NormalizedPath $file)
    }
}

function Get-UnprocessedChessComFiles {
    $processed = Get-ProcessedSet
    return @(
        Get-ChildItem data\raw -Filter "chesscom_*.pgn4.txt" -File |
            Sort-Object Name |
            Where-Object { -not $processed.Contains((Get-NormalizedPath $_)) }
    )
}

function Invoke-ChessComFileBatch {
    param([System.IO.FileInfo[]]$Files, [int]$Batch)
    $batchName = "chesscom_batch{0:D2}" -f $Batch
    $jsonl = "data\puzzles\$batchName.jsonl"
    $report = "data\puzzles\${batchName}_report.jsonl"
    $html = "data\puzzles\${batchName}_review.html"
    $args = @("-m", "schess_puzzles.cli", "select-batch")
    foreach ($file in $Files) {
        $args += $file.FullName
    }
    $args += @(
        "--limit", "0",
        "--depth", "10",
        "--multipv", "6",
        "--confirm-depth", "20",
        "--confirm-multipv", "6",
        "--extend-critical",
        "--max-plies", "5",
        "--output-jsonl", $jsonl,
        "--report-jsonl", $report
    )
    Invoke-Step $args
    Invoke-Step @("-m", "schess_puzzles.cli", "refresh-report-flags", $report)
    Invoke-Step @("-m", "schess_puzzles.cli", "review-html", $report, $html)
    Add-ProcessedFiles $Files
}

if (-not $env:CHESSCOM_COOKIE -and (Test-Path -LiteralPath $CookieFile)) {
    $env:CHESSCOM_COOKIE = Get-Content -LiteralPath $CookieFile -Raw
}
if (-not $env:CHESSCOM_COOKIE) {
    throw "Set CHESSCOM_COOKIE or provide -CookieFile pointing to the formatted cookie file."
}

New-Item -ItemType Directory -Force -Path logs | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logPath = "logs\chesscom_unattended_$timestamp.log"
Start-Transcript -Path $logPath | Out-Null
try {
    Write-Host "Unattended Chess.com run started at $(Get-Date)"
    Write-Host "Log: $logPath"
    Write-Host "Starting raw games: $(Get-RawChessComCount)"
    Write-Host "Next batch before run: $(Get-NextChessComBatch)"
    Initialize-ProcessedManifest

    $pagesDone = 0
    $batchesDone = 0
    while ($pagesDone -lt $ArchivePages -and $batchesDone -lt $MaxBatches) {
        $page = $ArchiveStartPage + $pagesDone
        $chunk = [Math]::Min($ArchiveChunkPages, $ArchivePages - $pagesDone)

        Invoke-Step @(
            "-m", "schess_puzzles.cli", "fetch-chesscom-archive",
            "--days", "0-9999",
            "--title", "seirawan",
            "--start-page", "$page",
            "--pages", "$chunk",
            "--delay", "$DownloadDelay"
        )
        $pagesDone += $chunk

        while ($batchesDone -lt $MaxBatches) {
            $unprocessed = Get-UnprocessedChessComFiles
            if ($unprocessed.Count -eq 0) {
                Write-Host "No newly downloaded files to process. raw=$(Get-RawChessComCount) nextBatch=$(Get-NextChessComBatch)"
                break
            }
            $batch = Get-NextChessComBatch
            $files = @($unprocessed | Select-Object -First $BatchSize)
            Invoke-ChessComFileBatch -Files $files -Batch $batch
            $batchesDone += 1
            if ($CombineAfterEachChunk) {
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
        }
    }

    if (-not $NoFinalCombine) {
        Invoke-Step @(
            "-m", "schess_puzzles.cli", "combine-reports",
            "--output", "data\puzzles\chesscom_all_report.jsonl"
        )
        Invoke-Step @(
            "-m", "schess_puzzles.cli", "review-html",
            "data\puzzles\chesscom_all_report.jsonl",
            "data\puzzles\chesscom_all_review.html"
        )
        Invoke-Step @(
            "-m", "schess_puzzles.cli", "combine-reports",
            "--glob", "data/puzzles/*_batch*_report.jsonl",
            "--output", "data\puzzles\all_report.jsonl"
        )
        Invoke-Step @(
            "-m", "schess_puzzles.cli", "review-html",
            "data\puzzles\all_report.jsonl",
            "data\puzzles\all_review.html"
        )
        Invoke-Step @("tools\status_summary.py")
    }

    Write-Host "Unattended Chess.com run finished at $(Get-Date)"
    Write-Host "Raw games: $(Get-RawChessComCount)"
    Write-Host "Next batch after run: $(Get-NextChessComBatch)"
} finally {
    Stop-Transcript | Out-Null
}
