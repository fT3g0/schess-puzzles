param(
    [string]$CookieFile = "cookies_env.txt",
    [string]$AccessTokenFile = "access_token.txt",
    [int]$AuthUserId = 7448926,
    [int]$ArchiveStartPage = 50,
    [int]$ArchivePages = 50,
    [int]$ArchiveChunkPages = 5,
    [double]$DownloadDelay = 1.0,
    [int]$BatchSize = 20,
    [int]$MaxBatches = 9999,
    [int]$Workers = 1,
    [int]$RescreenDepth = 14,
    [int]$RescreenMultiPv = 8,
    [int]$RescreenMinGapCp = 80,
    [int]$RescreenMarginCp = 120,
    [int]$FetchRetries = 3,
    [int]$FetchRetryDelaySeconds = 20,
    [switch]$Profile,
    [switch]$ProcessExistingOnly,
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

function Invoke-StepWithRetry {
    param(
        [string[]]$CommandArgs,
        [int]$Retries = 3,
        [int]$DelaySeconds = 20
    )
    $attempt = 1
    while ($true) {
        try {
            Invoke-Step $CommandArgs
            return
        } catch {
            if ($attempt -ge $Retries) {
                throw
            }
            Write-Warning "Command failed on attempt $attempt/$($Retries): $($_.Exception.Message)"
            Write-Host "Retrying in $DelaySeconds second(s)..."
            Start-Sleep -Seconds $DelaySeconds
            $attempt += 1
        }
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
    param([System.IO.FileInfo[]]$Files, [int]$Batch, [switch]$SkipManifest)
    $batchName = "chesscom_batch{0:D2}" -f $Batch
    $jsonl = "data\puzzles\$batchName.jsonl"
    $report = "data\puzzles\${batchName}_report.jsonl"
    $html = "data\puzzles\${batchName}_review.html"
    $evalCache = "data\cache\evals\$batchName"
    $profilePath = "data\profiles\${batchName}_selector.jsonl"
    $args = @("-m", "schess_puzzles.cli", "select-batch")
    foreach ($file in $Files) {
        $args += $file.FullName
    }
    $args += @(
        "--limit", "0",
        "--depth", "10",
        "--multipv", "6",
        "--rescreen-depth", "$RescreenDepth",
        "--rescreen-multipv", "$RescreenMultiPv",
        "--rescreen-min-gap-cp", "$RescreenMinGapCp",
        "--rescreen-margin-cp", "$RescreenMarginCp",
        "--confirm-depth", "20",
        "--confirm-multipv", "3",
        "--confirm-fast-depth", "17",
        "--extend-critical",
        "--max-plies", "7",
        "--extension-beam-width", "2",
        "--eval-cache-dir", $evalCache,
        "--output-jsonl", $jsonl,
        "--report-jsonl", $report
    )
    if ($Profile) {
        New-Item -ItemType Directory -Force -Path "data\profiles" | Out-Null
        if (Test-Path $profilePath) { Remove-Item -LiteralPath $profilePath -Force }
        $args += @("--profile-jsonl", $profilePath)
    }
    Invoke-Step $args
    Invoke-Step @("-m", "schess_puzzles.cli", "refresh-report-flags", $report)
    Invoke-Step @("-m", "schess_puzzles.cli", "review-html", $report, $html)
    if (-not $SkipManifest) { Add-ProcessedFiles $Files }
    if ($Profile -and (Test-Path $profilePath)) {
        Invoke-Step @("tools\summarize_profile.py", $profilePath)
    }
}

function Invoke-ChessComFileBatchJob {
    param([System.IO.FileInfo[]]$Files, [int]$Batch)
    if ($Workers -le 1) {
        Invoke-ChessComFileBatch -Files $Files -Batch $Batch
        return
    }
    $root = (Get-Location).Path
    $serializedFiles = @($Files | ForEach-Object { $_.FullName })
    $profileEnabled = [bool]$Profile
    $job = Start-Job -Name ("chesscom_batch{0:D2}" -f $Batch) -ScriptBlock {
        param($Root, $FilePaths, $BatchNumber, $ProfileEnabled, $RescreenDepth, $RescreenMultiPv, $RescreenMinGapCp, $RescreenMarginCp)
        Set-Location $Root
        $batchName = "chesscom_batch{0:D2}" -f $BatchNumber
        $jsonl = "data\puzzles\$batchName.jsonl"
        $report = "data\puzzles\${batchName}_report.jsonl"
        $html = "data\puzzles\${batchName}_review.html"
        $evalCache = "data\cache\evals\$batchName"
        $profilePath = "data\profiles\${batchName}_selector.jsonl"
        $args = @("-m", "schess_puzzles.cli", "select-batch")
        foreach ($file in $FilePaths) { $args += $file }
        $args += @(
            "--limit", "0",
            "--depth", "10",
            "--multipv", "6",
            "--rescreen-depth", "$RescreenDepth",
            "--rescreen-multipv", "$RescreenMultiPv",
            "--rescreen-min-gap-cp", "$RescreenMinGapCp",
            "--rescreen-margin-cp", "$RescreenMarginCp",
            "--confirm-depth", "20",
            "--confirm-multipv", "3",
            "--confirm-fast-depth", "17",
            "--extend-critical",
            "--max-plies", "7",
            "--extension-beam-width", "2",
            "--eval-cache-dir", $evalCache,
            "--output-jsonl", $jsonl,
            "--report-jsonl", $report
        )
        if ($ProfileEnabled) {
            New-Item -ItemType Directory -Force -Path "data\profiles" | Out-Null
            if (Test-Path $profilePath) { Remove-Item -LiteralPath $profilePath -Force }
            $args += @("--profile-jsonl", $profilePath)
        }
        Write-Host ""
        Write-Host "> python $($args -join ' ')"
        & python @args
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        & python -m schess_puzzles.cli refresh-report-flags $report
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        & python -m schess_puzzles.cli review-html $report $html
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        if ($ProfileEnabled -and (Test-Path $profilePath)) {
            & python tools\summarize_profile.py $profilePath
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        }
    } -ArgumentList $root, $serializedFiles, $Batch, $profileEnabled, $RescreenDepth, $RescreenMultiPv, $RescreenMinGapCp, $RescreenMarginCp
    Add-Member -InputObject $job -MemberType NoteProperty -Name FilePaths -Value $serializedFiles
    return $job
}
if (-not $env:CHESSCOM_COOKIE -and (Test-Path -LiteralPath $CookieFile)) {
    $env:CHESSCOM_COOKIE = Get-Content -LiteralPath $CookieFile -Raw
}
if (-not $env:CHESSCOM_COOKIE -and -not (Test-Path -LiteralPath $AccessTokenFile)) {
    throw "Set CHESSCOM_COOKIE, provide -CookieFile, or provide -AccessTokenFile."
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
    while (($ProcessExistingOnly -or $pagesDone -lt $ArchivePages) -and $batchesDone -lt $MaxBatches) {
        if (-not $ProcessExistingOnly) {
            $page = $ArchiveStartPage + $pagesDone
            $chunk = [Math]::Min($ArchiveChunkPages, $ArchivePages - $pagesDone)

            Invoke-StepWithRetry -Retries $FetchRetries -DelaySeconds $FetchRetryDelaySeconds -CommandArgs @(
                "-m", "schess_puzzles.cli", "fetch-chesscom-archive",
                "--access-token-file", $AccessTokenFile,
                "--auth-user-id", "$AuthUserId",
                "--days", "0-9999",
                "--title", "seirawan",
                "--start-page", "$page",
                "--pages", "$chunk",
                "--delay", "$DownloadDelay"
            )
            $pagesDone += $chunk
        }

        while ($batchesDone -lt $MaxBatches) {
            $unprocessed = @(Get-UnprocessedChessComFiles)
            if ($unprocessed.Count -eq 0) {
                Write-Host "No newly downloaded files to process. raw=$(Get-RawChessComCount) nextBatch=$(Get-NextChessComBatch)"
                break
            }
            $waveSize = [Math]::Min([Math]::Max($Workers, 1), $MaxBatches - $batchesDone)
            $jobs = @()
            $batchBase = Get-NextChessComBatch
            for ($i = 0; $i -lt $waveSize; $i++) {
                $offset = $i * $BatchSize
                $files = @($unprocessed | Select-Object -Skip $offset -First $BatchSize)
                if ($files.Count -eq 0) { break }
                $batch = $batchBase + $i
                if ($Workers -le 1) {
                    Invoke-ChessComFileBatch -Files $files -Batch $batch
                    $batchesDone += 1
                } else {
                    Write-Host "Queueing chesscom_batch$('{0:D2}' -f $batch) files=$($files.Count)"
                    $jobs += Invoke-ChessComFileBatchJob -Files $files -Batch $batch
                }
            }
            if ($Workers -gt 1 -and $jobs.Count) {
                Write-Host "Waiting for $($jobs.Count) worker(s)..."
                Wait-Job -Job $jobs | Out-Null
                $failed = $false
                foreach ($job in $jobs) {
                    Write-Host ""
                    Write-Host "--- Worker $($job.Name) output ---"
                    Receive-Job -Job $job
                    if ($job.State -ne "Completed") {
                        $failed = $true
                    } else {
                        $processedFiles = @($job.FilePaths | ForEach-Object { Get-Item -LiteralPath $_ })
                        Add-ProcessedFiles $processedFiles
                    }
                    Remove-Job -Job $job
                }
                if ($failed) { throw "At least one Chess.com worker failed." }
                $batchesDone += $jobs.Count
            }
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
        if ($ProcessExistingOnly) { break }
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
